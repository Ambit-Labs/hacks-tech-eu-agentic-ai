"""Column mapping: which layout a header picks, and which column each field gets.

Fixtures are the header rows themselves, typed out from the real files. No
real data file is copied into the repo.
"""

from __future__ import annotations

import pytest

from scrooge_indexer.loader.mappings import (
    LAYOUTS,
    SPEND_BOROUGHS,
    date_headers,
    header_markers,
    normalise,
    resolve,
)

BARNET_OLD = [
    "Directorate",
    "Department",
    "Expenditure Type",
    "Ref.Doc.1",
    "Vendor Name",
    "Expenditure Amount (exc VAT)",
    "Payment Date",
]
BARNET_NEW = [
    "Cost Centre Hierarchy - Directorate",
    "Cost Centre Hierarchy - Department",
    "Expenditure Type",
    "Payment Reference Number",
    "Payment Number",
    "Supplier Name",
    "Distribution Amount",
    "Payment Date",
]
HAVERING_NEW = [
    "Body",
    "Body Name",
    "Transaction Date",
    "Beneficiary",
    "Local Authority Department",
    "Purpose of Expenditure",
    "Amount (excluding VAT)",
    "Non Recoverable VAT",
    "Merchant Category",
]
HAVERING_OLD = [
    "Body",
    "Body Name",
    "Posted Fiscal Date",
    "Amount",
    "Transaction Number",
    "Supplier Name",
    "Directorate",
    "Service",
    "Activity",
    "Cost Centre Name",
    "Subjective Name",
]


def test_every_borough_has_at_least_one_layout():
    assert set(SPEND_BOROUGHS) == set(LAYOUTS)
    for borough, layouts in LAYOUTS.items():
        assert layouts, borough


def test_matching_ignores_case_and_whitespace():
    header = ["  payment   DATE ", "VENDOR name", "expenditure amount (exc vat)"]
    mapping = resolve("barnet", header)
    assert mapping is not None
    assert mapping.columns["payment_date"] == 0
    assert mapping.columns["supplier"] == 1
    assert mapping.columns["amount_gbp"] == 2


def test_non_breaking_space_in_a_header():
    assert normalise("Vendor Name 2") == "vendor name 2"


def test_barnet_layouts_are_told_apart_by_their_headers():
    old = resolve("barnet", BARNET_OLD)
    new = resolve("barnet", BARNET_NEW)
    assert old is not None and old.layout == "old"
    assert new is not None and new.layout == "new"
    assert old.columns["supplier"] == BARNET_OLD.index("Vendor Name")
    assert new.columns["supplier"] == BARNET_NEW.index("Supplier Name")


def test_barnet_reference_prefers_payment_reference_number():
    """The doc says the first of the two is the reference."""
    mapping = resolve("barnet", BARNET_NEW)
    assert mapping.columns["reference"] == BARNET_NEW.index("Payment Reference Number")


def test_barnet_2025_10_falls_back_to_payment_number():
    """That one file lost the reference header and repeats `Payment Number`."""
    header = [
        "Cost Centre Hierarchy - Directorate",
        "Cost Centre Hierarchy - Department",
        "Payment Number",
        "Expenditure Type",
        "Payment Number",
        "Supplier Name",
        "Distribution Amount",
        "Payment Date",
    ]
    mapping = resolve("barnet", header)
    assert mapping.layout == "new"
    assert mapping.columns["reference"] == 2


def test_havering_layouts_are_told_apart():
    new = resolve("havering", HAVERING_NEW)
    old = resolve("havering", HAVERING_OLD)
    assert new.layout == "new"
    assert old.layout == "old"
    assert new.columns["directorate"] == HAVERING_NEW.index(
        "Local Authority Department"
    )
    assert old.columns["department"] == HAVERING_OLD.index("Service")
    assert old.columns["purpose"] == HAVERING_OLD.index("Subjective Name")


def test_havering_2010_files_have_a_purpose():
    """December 2010 to March 2011 call it `Expenses Type`, 22,590 rows."""
    header = [
        "Body",
        "Body Name",
        "Date",
        "Transaction Number",
        "Amount",
        "Supplier Name",
        "Vendor Number",
        "Expenses Type",
        "Service Area Categorization",
        "DIR",
        "SERV",
    ]
    mapping = resolve("havering", header)
    assert mapping.layout == "old"
    assert mapping.columns["purpose"] == header.index("Expenses Type")


def test_bexley_pound_sign_is_the_amount_column():
    header = [
        "Payment Date",
        "Transaction Number",
        "£",
        "Non recoverable VAT £",
        "Supplier",
        "Supplier Number",
        "Directorate",
        "Service Area",
        "Description",
    ]
    mapping = resolve("bexley", header)
    assert mapping.columns["amount_gbp"] == 2
    assert mapping.columns["vat_gbp"] == 3
    assert mapping.columns["purpose"] == 8


def test_bexley_cp1252_mojibake_amount_header():
    header = ["Payment Date", "Transcation Number", "œ", "Supplier", "Service Area"]
    mapping = resolve("bexley", header)
    assert mapping.columns["amount_gbp"] == 2
    assert mapping.columns["reference"] == 1


def test_westminster_prefers_the_final_supplier_name():
    header = [
        "Posting date",
        "Supplier number",
        "Supplier name",
        "FINAL Supplier name",
        "Expense type",
        "Department",
        "Amount",
    ]
    mapping = resolve("westminster", header)
    assert mapping.columns["supplier"] == header.index("FINAL Supplier name")


def test_lambeth_transparency_report_beats_the_transactions_layout():
    header = [
        "Over £500 Report Ref",
        "PAYMENT_DATE",
        "Supplier Name *******",
        "Vendor Type",
        "Amount",
        "Directorate",
        "Division",
        "Subjective Description",
        "Accounting Date",
        "Invoice Creation Date",
    ]
    mapping = resolve("lambeth", header)
    assert mapping.layout == "transparency report"
    assert mapping.columns["payment_date"] == header.index("PAYMENT_DATE")


def test_lambeth_warehouse_layout():
    header = [
        "Invoice_Payment_Date",
        "Org_Level_2_Desc",
        "Supplier_Name",
        "Nominal_Desc",
        "Invoice_Line_Net_Amount",
        "Internal_Category_Code",
    ]
    mapping = resolve("lambeth", header)
    assert mapping.layout == "warehouse"
    assert mapping.columns["amount_gbp"] == 4


def test_redbridge_picks_account_description_for_purpose():
    header = [
        "Directorate",
        "Service",
        "Bvsub Description",
        "Bvsum Description",
        "Account Description",
        "Transaction No",
        "Transaction Date",
        "Amount",
        "Classification Description",
        "Supplier Description",
    ]
    mapping = resolve("redbridge", header)
    assert mapping.columns["purpose"] == header.index("Account Description")


def test_wandsworth_july_2024_duplicate_amount_header():
    """The date column is headed `PAYMENT AMOUNT` and the real one is missing."""
    header = [
        "DIRECTORATE",
        "PAYMENT AMOUNT",
        "PAYMENT AMOUNT",
        "PAYEE",
        "SUPPLIER NO",
        "ACTIVITY",
    ]
    mapping = resolve("wandsworth", header)
    assert mapping is not None
    assert mapping.columns["payment_date"] == 1
    assert mapping.columns["amount_gbp"] == 2
    assert "payment amount" in header_markers("wandsworth")


def test_wandsworth_repair_leaves_a_normal_header_alone():
    header = ["PAYMENT DATE", "PAYEE", "PAYMENT AMOUNT", "DIRECTORATE", "ACTIVITY"]
    mapping = resolve("wandsworth", header)
    assert mapping.columns["payment_date"] == 0
    assert mapping.columns["amount_gbp"] == 2


def test_a_header_without_the_three_required_columns_does_not_resolve():
    assert resolve("lambeth", ["Supplier Name", "Total"]) is None
    assert resolve("camden", ["something", "else"]) is None


def test_unknown_borough_resolves_to_nothing():
    assert resolve("bromley", ["Payment Date", "Supplier", "Amount"]) is None


@pytest.mark.parametrize("borough", SPEND_BOROUGHS)
def test_date_headers_are_normalised(borough):
    headers = date_headers(borough)
    assert headers
    assert all(header == normalise(header) for header in headers)
