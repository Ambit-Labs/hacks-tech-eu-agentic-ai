"""Building payment tuples: what is dropped, what is skipped, what `raw` holds."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from scrooge_indexer.loader.mappings import resolve
from scrooge_indexer.loader.readers import Table
from scrooge_indexer.loader.rows import (
    DAY_FIRST,
    MIXED,
    MONTH_FIRST,
    AmbiguousDateOrder,
    RowStats,
    detect_date_order,
    payment_rows,
    raw_keys,
)

HEADER = ["PAYMENT DATE", "PAYEE", "PAYMENT AMOUNT", "DIRECTORATE", "ACTIVITY"]


def table_of(rows, header=HEADER):
    return Table(
        header=header,
        rows=iter(rows),
        encoding="utf-8-sig",
        delimiter=",",
        header_row=0,
    )


def build(rows, header=HEADER, borough="wandsworth", date_order=DAY_FIRST):
    table = table_of(rows, header)
    mapping = resolve(borough, header)
    stats = RowStats()
    built = list(
        payment_rows(
            table,
            mapping,
            borough=borough,
            source_file="data/raw/x/y.csv",
            stats=stats,
            date_order=date_order,
        )
    )
    return built, stats


def order_of(dates, header=HEADER, borough="wandsworth"):
    rows = [[d, "A LTD", "500", "H", "R"] for d in dates]
    return detect_date_order(table_of(rows, header), resolve(borough, header))


def test_a_clean_row():
    built, stats = build([["02/01/2019", "A LTD", "1,500.00", "Housing", "Repairs"]])
    (row,) = built
    assert row[0] == "wandsworth"
    assert row[1] == date(2019, 1, 2)
    assert row[2] == "2018/19"
    assert row[3] == "A LTD"
    assert row[4] == "Housing"
    assert row[5] is None  # wandsworth publishes no department
    assert row[6] == "Repairs"
    assert row[7] == Decimal("1500.00")
    assert row[8] is None
    assert row[11] == 1
    assert stats.loaded == 1
    assert stats.reason() is None


def test_source_row_counts_every_data_row_so_drops_leave_gaps():
    built, stats = build(
        [
            ["02/01/2019", "A LTD", "500", "H", "R"],
            ["N/A", "B LTD", "500", "H", "R"],
            ["", "", "", "", ""],
            ["04/01/2019", "C LTD", "500", "H", "R"],
        ]
    )
    assert [row[11] for row in built] == [1, 4]
    assert stats.blank == 1
    assert stats.dropped_total == 1


def test_a_bad_date_drops_the_row_and_is_counted():
    built, stats = build(
        [
            ["N/A", "A LTD", "500", "H", "R"],
            ["nonsense", "B LTD", "500", "H", "R"],
            ["", "C LTD", "500", "H", "R"],
        ]
    )
    assert built == []
    assert stats.dropped == {"bad date": 2, "empty date": 1}
    assert stats.reason() == "3 rows dropped: 2 bad date, 1 empty date"


def test_an_empty_supplier_drops_the_row():
    built, stats = build([["02/01/2019", "   ", "500", "H", "R"]])
    assert built == []
    assert stats.dropped == {"empty supplier": 1}


def test_an_unparseable_amount_drops_the_row():
    built, stats = build([["02/01/2019", "A LTD", "see note", "H", "R"]])
    assert built == []
    assert stats.dropped == {"bad amount": 1}


def test_blank_and_marker_rows_are_not_failures():
    """A fully blank row, a Bexley month marker and a footer total."""
    built, stats = build(
        [
            ["", "", "", "", ""],
            ["APRIL", "", "", "", ""],
            ["Total", "", "", "", ""],
        ]
    )
    assert built == []
    assert stats.blank == 3
    assert stats.dropped_total == 0
    assert stats.reason() is None


def test_raw_holds_every_published_cell_under_its_header():
    built, _ = build([["02/01/2019", "A LTD", "500", "Housing", "Repairs"]])
    raw = built[0][12].obj
    assert raw == {
        "PAYMENT DATE": "02/01/2019",
        "PAYEE": "A LTD",
        "PAYMENT AMOUNT": "500",
        "DIRECTORATE": "Housing",
        "ACTIVITY": "Repairs",
    }


def test_raw_keeps_blank_trailing_columns_and_repeated_headers():
    header = ["Payment Date", "Supplier", "Amount", "", "Amount"]
    keys = raw_keys(header)
    assert keys == ["Payment Date", "Supplier", "Amount", "#4", "Amount #2"]


def test_raw_names_a_cell_past_the_end_of_the_header():
    header = ["PAYMENT DATE", "PAYEE", "PAYMENT AMOUNT"]
    built, _ = build([["02/01/2019", "A LTD", "500", "extra"]], header=header)
    assert built[0][12].obj["#4"] == "extra"


def test_a_short_row_simply_has_fewer_keys():
    built, _ = build([["02/01/2019", "A LTD", "500"]])
    raw = built[0][12].obj
    assert set(raw) == {"PAYMENT DATE", "PAYEE", "PAYMENT AMOUNT"}
    assert built[0][4] is None


def test_financial_year_boundaries_across_a_file():
    built, _ = build(
        [
            ["31/03/2020", "A LTD", "500", "H", "R"],
            ["01/04/2020", "B LTD", "500", "H", "R"],
        ]
    )
    assert [row[2] for row in built] == ["2019/20", "2020/21"]


def test_a_date_with_no_day_first_reading_stops_the_file():
    """The runner catches this, scans the column, and loads the file again."""
    with pytest.raises(AmbiguousDateOrder, match="row 2"):
        build(
            [
                ["07/03/2020", "A LTD", "500", "H", "R"],
                ["09/18/2020", "B LTD", "500", "H", "R"],
            ]
        )


def test_a_month_first_file_loads_once_the_order_is_known():
    """Lambeth 2020-Q2: 18 September, and 3 July rather than 7 March."""
    built, stats = build(
        [
            ["09/18/2020", "A LTD", "500", "H", "R"],
            ["07/03/2020", "B LTD", "500", "H", "R"],
        ],
        date_order=MONTH_FIRST,
    )
    assert [row[1] for row in built] == [date(2020, 9, 18), date(2020, 7, 3)]
    assert stats.dropped_total == 0


def test_a_parenthesised_amount_is_a_negative():
    built, _ = build([["02/01/2019", "A LTD", "(559.33)", "H", "R"]])
    assert built[0][7] == Decimal("-559.33")


# --------------------------------------------------------------------------- #
# detect_date_order
# --------------------------------------------------------------------------- #


def test_detect_month_first():
    """At least one second number over 12, and no first number over 12."""
    assert order_of(["09/18/2020", "07/03/2020", "09/10/2020"]) == MONTH_FIRST


def test_detect_day_first():
    assert order_of(["18/09/2020", "03/07/2020", "10/09/2020"]) == DAY_FIRST


def test_detect_mixed_fails():
    """Both kinds present, so no single reading fits the column."""
    assert order_of(["09/18/2020", "18/09/2020"]) == MIXED


def test_detect_leaves_an_entirely_ambiguous_file_day_first():
    """Every date has both readings, so the day-first rule stands."""
    assert order_of(["07/03/2020", "01/02/2020", "12/11/2020"]) == DAY_FIRST


def test_detect_ignores_forms_that_are_never_month_first():
    assert order_of(["13-08-2021", "14.06.2018", "23-Apr-2024", ""]) == DAY_FIRST


def test_detect_holds_no_rows():
    """The scan keeps two booleans, so a 20 MB quarter costs no memory."""
    consumed = []

    def dates():
        for value in ("09/18/2020", "07/03/2020"):
            consumed.append(value)
            yield [value, "A LTD", "500", "H", "R"]

    table = Table(
        header=HEADER,
        rows=dates(),
        encoding="utf-8-sig",
        delimiter=",",
        header_row=0,
    )
    assert detect_date_order(table, resolve("wandsworth", HEADER)) == MONTH_FIRST
    assert consumed == ["09/18/2020", "07/03/2020"]


def test_negative_amounts_stay_negative():
    built, _ = build([["02/01/2019", "A LTD", "-£177,790.95", "H", "R"]])
    assert built[0][7] == Decimal("-177790.95")


def test_vat_is_read_when_the_borough_publishes_it():
    header = [
        "Payment Date",
        "Vendor Name 2",
        "Cost Centre Description",
        "Subjective desctiption",
        "Amount",
        "Non Recoverable VAT",
    ]
    built, _ = build(
        [["09/11/2023", " TKE UK Ltd", "Ppm M and E", "Works", "2672.82", "12.50"]],
        header=header,
        borough="brent",
    )
    assert built[0][7] == Decimal("2672.82")
    assert built[0][8] == Decimal("12.50")
    assert built[0][3] == "TKE UK Ltd"  # trimmed, nothing else
