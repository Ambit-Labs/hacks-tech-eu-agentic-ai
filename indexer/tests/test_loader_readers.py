"""Reading a file: encoding, delimiter, header row, and the rows after it.

Fixtures are written into tmp_path from inline strings and bytes. Nothing here
opens a real spend file, and the awkward shapes the schema doc names are
reproduced in miniature rather than copied.
"""

from __future__ import annotations

import pytest

from scrooge_indexer.loader.mappings import header_markers, resolve
from scrooge_indexer.loader.readers import (
    NoHeader,
    ReadError,
    find_header,
    open_table,
    sniff_delimiter,
    sniff_encoding,
)


def write(tmp_path, name: str, text: str, encoding: str = "utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def rows_of(path, borough):
    with open_table(path, header_markers(borough)) as table:
        return table, list(table.rows)


# --------------------------------------------------------------------------- #
# encoding
# --------------------------------------------------------------------------- #


def test_utf8_with_a_bom(tmp_path):
    path = write(tmp_path, "a.csv", "PAYMENT DATE,PAYEE\n", encoding="utf-8-sig")
    assert sniff_encoding(path) == "utf-8-sig"


def test_cp1252_falls_back(tmp_path):
    path = tmp_path / "b.csv"
    path.write_bytes(b"Payment Date,Supplier\r\n01/04/2016,ANDR\x89 LTD\r\n")
    assert sniff_encoding(path) == "cp1252"


def test_a_cp1252_pound_sign_reads_as_mojibake(tmp_path):
    """0x9C is `œ` in cp1252, which is how `£` survives a bad round trip."""
    path = tmp_path / "c.csv"
    path.write_bytes(b"Payment Date,\x9c,Supplier\r\n01/04/2016,600,A LTD\r\n")
    table, rows = rows_of(path, "bexley")
    assert table.encoding == "cp1252"
    assert table.header[1] == "œ"
    assert resolve("bexley", table.header).columns["amount_gbp"] == 1


def test_a_file_clean_for_a_megabyte_and_broken_later(tmp_path):
    """The probe reads the whole file, so a late cp1252 byte still decides."""
    path = tmp_path / "d.csv"
    padding = b"Payment Date,Supplier\r\n" + b"01/04/2016,A LTD\r\n" * 60_000
    path.write_bytes(padding + b"01/04/2016,ANDR\x89 LTD\r\n")
    assert sniff_encoding(path) == "cp1252"


# --------------------------------------------------------------------------- #
# delimiter
# --------------------------------------------------------------------------- #


def test_comma_is_the_usual_answer():
    assert sniff_delimiter("a,b,c\n1,2,3\n") == ","


def test_tab_delimited(tmp_path):
    text = "Transaction Date\tBENEFICIARY\tAmount\n01/04/2019\tA LTD\t500\n"
    path = write(tmp_path, "t.csv", text)
    table, rows = rows_of(path, "newham")
    assert table.delimiter == "\t"
    assert rows == [["01/04/2019", "A LTD", "500"]]


def test_a_semicolon_file():
    assert sniff_delimiter("a;b;c\n1;2;3\n") == ";"


# --------------------------------------------------------------------------- #
# the header row
# --------------------------------------------------------------------------- #


def test_title_row_before_the_header(tmp_path):
    """Bexley and Brent put a title and a blank line in front of the header."""
    text = (
        "Bexley payments over £500,,\n"
        ",,\n"
        "Payment Date,Supplier,Amount\n"
        "11/10/2019,A LTD,500\n"
    )
    path = write(tmp_path, "bexley.csv", text)
    table, rows = rows_of(path, "bexley")
    assert table.header_row == 2
    assert rows == [["11/10/2019", "A LTD", "500"]]


def test_lewisham_header_on_row_three(tmp_path):
    text = (
        ",,Lewisham Council Expenditure over £250 February 2023,,,\n"
        ",,,,,\n"
        "PAYMENT DATE,SUPPLIER,SERVICE,DEPARTMENT,DESCRIPTION,"
        "£ SPEND (EXCLUDING VAT)\n"
        "01/02/2023,42 Bedford Row,LITIGATION,LAW,SALARIES,400\n"
    )
    path = write(tmp_path, "lewisham.csv", text)
    table, rows = rows_of(path, "lewisham")
    assert table.header_row == 2
    assert len(rows) == 1


def test_hounslow_leaked_sql_and_the_extra_leading_column(tmp_path):
    """Two headers in a row, and the second one is the real one."""
    text = (
        '"SELECT upper(dir.DESCRIPTION) OrganisationalUnit,\n'
        '  ap.PAYMENT_DATE PaymentDate\n"\n'
        "SET DATE_FROM =01/03/2021\n"
        "SET DATE_TO = 31/03/2021\n"
        "columns,OrganisationalUnit,ServiceCategoryLabel,,BeneficiaryName,"
        "SupplierName,PaymentDate,TransactionNumber,Amount,"
        "IrrecoverableVATAmount,Purpose,CategoryInternalName\n"
        ",OrganisationalUnit,ServiceCategoryLabel,Redaction Necessary,"
        "BeneficiaryName,SupplierName,PaymentDate,TransactionNumber,Amount,"
        "IrrecoverableVATAmount,Purpose,CategoryInternalName\n"
        "INSERTED DETAIL,CAPITAL HRA,Housing,,A LTD,A LTD,05/03/2021,4974526,"
        "3500.00,0.00,PAYMENT TO MAIN CONTRACTOR,Suppliers\n"
    )
    path = write(tmp_path, "hounslow.csv", text)
    table, rows = rows_of(path, "hounslow")
    assert table.header_row == 4
    assert table.header[3] == "Redaction Necessary"
    mapping = resolve("hounslow", table.header)
    assert mapping.columns["payment_date"] == 6
    assert mapping.columns["supplier"] == 4
    assert rows[0][6] == "05/03/2021"


def test_carriage_return_only_line_endings(tmp_path):
    """Hounslow 2021-08 and two Havering months end records with a bare CR."""
    text = (
        "OrganisationalUnit,BeneficiaryName,PaymentDate,Amount\r"
        "CAPITAL HRA,21 DEGREES LTD,13/08/2021,23312.00\r"
        "HOUSING,A AND R LTD,20/08/2021,4000.00\r"
    )
    path = write(tmp_path, "cr.csv", text)
    table, rows = rows_of(path, "hounslow")
    assert table.header_row == 0
    assert len(rows) == 2


def test_a_headerless_file_says_so(tmp_path):
    text = "30/06/2015,,,,\n05/07/2015,343371,1544.49,0,A PILE & SON LIMITED\n"
    path = write(tmp_path, "headerless.csv", text)
    with pytest.raises(NoHeader) as caught:
        rows_of(path, "bexley")
    assert caught.value.rows[0][0] == "30/06/2015"


def test_find_header_takes_the_first_of_two_far_apart():
    rows = [["Payment Date", "Supplier"], ["01/01/2019", "A"], ["Payment Date", "x"]]
    assert find_header(rows, ("payment date",)) == 0


# --------------------------------------------------------------------------- #
# formats
# --------------------------------------------------------------------------- #


def test_ods_is_refused_by_name(tmp_path):
    path = write(tmp_path, "lambeth.ods", "not really an ods")
    with pytest.raises(ReadError, match="no ODS reader"):
        rows_of(path, "lambeth")


def test_an_xls_workbook_with_a_csv_extension(tmp_path):
    """Newham's February 2019 file is an OLE2 workbook called `.csv`."""
    path = tmp_path / "newham.csv"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200)
    with pytest.raises(ReadError, match="Excel 97"):
        rows_of(path, "newham")


def test_xlsx_with_a_leading_options_sheet(tmp_path):
    """Hounslow's 2025 xlsx files put an `_options` sheet before the data."""
    openpyxl = pytest.importorskip("openpyxl")
    from datetime import datetime

    workbook = openpyxl.Workbook()
    options = workbook.active
    options.title = "_options"
    options.append(["* This sheet is manipulated by the 'Options...' dialog"])
    sheet = workbook.create_sheet("Sheet1")
    sheet.append(
        [
            "OrganisationalUnit",
            "ServiceCategoryLabel",
            "BeneficiaryName",
            "SupplierID",
            "PaymentDate",
            "TransactionNumber",
            "Amount",
            "IrrecoverableVATAmount",
            "Purpose",
            "CategoryInternalName",
        ]
    )
    sheet.append(
        [
            "RESOURCES",
            "Revenue Recharges",
            "11 KBW LTD",
            512474,
            datetime(2025, 7, 1),
            5621675,
            1152,
            0,
            "SERVICES/FEES",
            "Suppliers",
        ]
    )
    path = tmp_path / "hounslow.xlsx"
    workbook.save(path)

    table, rows = rows_of(path, "hounslow")
    assert table.sheet == "Sheet1"
    assert table.header_row == 0
    assert rows[0][4] == datetime(2025, 7, 1)
