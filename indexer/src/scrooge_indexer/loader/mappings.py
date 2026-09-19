"""Which published column is which typed column, per borough and layout.

Data, not logic. The table in docs/payments-schema.md is the contract; this
module is that table written as tuples, plus the header spellings the real
files on disk use that the doc does not list. The doc's own name is always
first in each tuple and a comment names the borough and the file family every
extra spelling came from, so nothing widens quietly.

Matching is on the header text with whitespace collapsed and case ignored,
which is what the doc asks for. A borough with more than one layout gets one
entry per layout and :func:`resolve` picks whichever fits the header in front
of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Fields in the order the loader writes them.
FIELDS = (
    "payment_date",
    "supplier",
    "directorate",
    "department",
    "purpose",
    "amount_gbp",
    "vat_gbp",
    "reference",
)

#: A row needs these three to be a payment at all.
REQUIRED = ("payment_date", "supplier", "amount_gbp")

_WHITESPACE = re.compile(r"\s+")


def normalise(header: str) -> str:
    """``"  Service  Area "`` and ``"SERVICE AREA"`` both become ``service area``."""
    return _WHITESPACE.sub(" ", str(header or "").replace(" ", " ")).strip().lower()


@dataclass(frozen=True)
class Layout:
    """One borough's column names for one of its layouts.

    Each field is an ordered tuple of candidate headers. The first one present
    in the file wins, which is how Westminster's `FINAL Supplier name` takes
    precedence over `Supplier name` in its 2024 files, and how Barnet's
    `Payment Reference Number` beats its `Payment Number`.
    """

    name: str
    payment_date: tuple[str, ...]
    supplier: tuple[str, ...]
    amount_gbp: tuple[str, ...]
    directorate: tuple[str, ...] = ()
    department: tuple[str, ...] = ()
    purpose: tuple[str, ...] = ()
    vat_gbp: tuple[str, ...] = ()
    reference: tuple[str, ...] = ()

    def candidates(self, name: str) -> tuple[str, ...]:
        return tuple(normalise(c) for c in getattr(self, name))


@dataclass(frozen=True)
class Mapping:
    """A layout bound to one file's header row: field name to column index."""

    borough: str
    layout: str
    columns: dict[str, int]
    header: tuple[str, ...]
    matched: int = field(default=0, compare=False)

    def index(self, name: str) -> int | None:
        return self.columns.get(name)


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

LAYOUTS: dict[str, tuple[Layout, ...]] = {
    "barnet": (
        Layout(
            name="old",
            payment_date=("Payment Date",),
            supplier=("Vendor Name", "Vendor", "Name"),  # 2014-08 and 2015-01
            directorate=("Directorate",),
            department=("Department", "Service Area"),  # 2013-14 whole-year file
            purpose=("Expenditure Type",),
            # The 2013-14 and two 2014 files name the same column after the
            # threshold that applied that year.
            amount_gbp=(
                "Expenditure Amount (exc VAT)",
                "Expenditure over £500 (exc VAT)",
            ),
            reference=("Ref.Doc.1", "Ref.Doc."),  # 2013-14 drops the 1
        ),
        Layout(
            name="new",
            payment_date=("Payment Date",),
            supplier=("Supplier Name",),
            directorate=("Cost Centre Hierarchy - Directorate",),
            department=("Cost Centre Hierarchy - Department",),
            purpose=("Expenditure Type",),
            amount_gbp=("Distribution Amount",),
            # 2025-10 lost the reference header and repeats `Payment Number`
            # in its place, so the fallback is the first of the two.
            reference=("Payment Reference Number", "Payment Number"),
        ),
    ),
    "bexley": (
        Layout(
            name="",
            payment_date=("Payment Date",),
            supplier=("Supplier",),
            directorate=("Directorate",),
            department=("Service area",),
            # Files before 2022 call the expense type `Description`.
            purpose=("Expense Type", "Description"),
            # `£` is the header on the pre-2022 amount column, and `œ` is what
            # two 2016 files contain because they were saved as cp1252.
            amount_gbp=("Amount", "£", "œ"),
            vat_gbp=(
                "Non Recoverable VAT",
                "Non recoverable VAT £",
                "Non-Recoverable VAT",
                "Non Recurring VAT",  # 2023-11 only
            ),
            reference=("Transaction Number", "Transcation Number", "Transaction No"),
        ),
    ),
    "brent": (
        Layout(
            name="",
            payment_date=("Payment Date",),
            supplier=("Vendor Name 2",),
            department=("Cost Centre Description",),
            purpose=("Subjective desctiption", "Subjective Description"),
            amount_gbp=("Amount",),
            vat_gbp=("Non Recoverable VAT",),
        ),
    ),
    "camden": (
        Layout(
            name="",
            payment_date=("payment_date",),
            supplier=("beneficiary_name",),
            directorate=("organisational_unit",),
            purpose=("purpose",),
            amount_gbp=("amount_gbp",),
            vat_gbp=("irrecoverable_vat_amount_gbp",),
            reference=("unique_identifier",),
        ),
    ),
    "haringey": (
        Layout(
            name="",
            payment_date=("Payment date",),
            supplier=("Supplier Name",),
            directorate=("Department",),
            purpose=("Purpose",),
            # Three quarters were exported straight out of a pivot table.
            amount_gbp=("Amount", "Sum of Amount"),
        ),
    ),
    "havering": (
        Layout(
            name="new",
            payment_date=("Transaction Date",),
            supplier=("Beneficiary",),
            directorate=("Local Authority Department",),
            purpose=("Purpose of Expenditure",),
            amount_gbp=("Amount (excluding VAT)",),
            vat_gbp=("Non Recoverable VAT",),
        ),
        Layout(
            name="old",
            # `Fiscal Date`, `Date`, `Invoice Receipt Date` and `Invoice
            # Received Date` are the 2011 to 2014 spellings of the same column.
            payment_date=(
                "Posted Fiscal Date",
                "Fiscal Date",
                "Invoice Receipt Date",
                "Invoice Received Date",
                "Date",
            ),
            supplier=("Supplier Name",),
            directorate=("Directorate", "Directorate Name", "Dir"),
            department=("Service", "Service Name", "Serv"),
            # `Expenses Type` is all the four files from 2010-12 to 2011-03
            # give: `Supplies and Services`, `Transfer Payments`.
            purpose=("Subjective Name", "Activity", "Activity Name", "Expenses Type"),
            # `Amount (£)` and `AP Document Amount` are the 2011 headers; the
            # `œ` and the lost bracket are the same header in cp1252 and in a
            # file somebody edited by hand.
            amount_gbp=(
                "Amount",
                "Amount (£)",
                "Amount (œ)",
                "Amount £)",
                "AP Document Amount",
                "AP Document Amount (£)",
            ),
            reference=("Transaction Number", "Purchase Invoice Number"),
        ),
    ),
    "hounslow": (
        Layout(
            name="",
            payment_date=("PaymentDate",),
            # Seven 2012 files publish only the unredacted supplier name.
            supplier=("BeneficiaryName", "SupplierName"),
            directorate=("OrganisationalUnit",),
            department=("ServiceCategoryLabel",),
            purpose=("Purpose",),
            amount_gbp=("Amount",),
            vat_gbp=("IrrecoverableVATAmount",),
            reference=("TransactionNumber",),
        ),
    ),
    "islington": (
        Layout(
            name="",
            payment_date=("Entry Date", "Transaction Date", "Input Date"),
            supplier=("Supplier Name",),
            directorate=("Department", "Directorate"),
            department=("Service",),
            purpose=("Spend Type", "Nominal Description"),
            amount_gbp=("Net Amount", "Amount"),
        ),
    ),
    "lambeth": (
        Layout(
            name="transparency report",
            payment_date=("PAYMENT_DATE", "Payment Date"),
            supplier=("Supplier Name *******", "Supplier Name*******"),
            directorate=("Directorate",),
            department=("Division",),
            purpose=("Subjective Description",),
            amount_gbp=("Amount",),
            reference=("Over £500 Report Ref",),
        ),
        Layout(
            name="transactions",
            payment_date=("Invoice Creation Date",),
            supplier=("Supplier Name",),
            directorate=("Department",),
            purpose=("Subj Description", "Subjective Name"),
            # The 2014 files drop a T from Nett.
            amount_gbp=("Invoice Nett Amount", "Invoice Net Amount"),
        ),
        Layout(
            # The 2015-16 and 2016-17 quarters came out of a different report
            # with underscored column names. Not in the schema doc.
            name="warehouse",
            payment_date=("Invoice_Payment_Date",),
            supplier=("Supplier_Name",),
            directorate=("Org_Level_2_Desc",),
            purpose=("Nominal_Desc",),
            amount_gbp=("Invoice_Line_Net_Amount",),
        ),
    ),
    "lewisham": (
        Layout(
            name="",
            payment_date=("PAYMENT DATE",),
            supplier=("SUPPLIER",),
            directorate=("DEPARTMENT",),
            department=("SERVICE",),
            purpose=("DESCRIPTION",),
            # Two months lost a bracket or a space from the header.
            amount_gbp=(
                "£ SPEND (EXCLUDING VAT)",
                "£ SPEND (EXCLUDING VAT",
                "£SPEND (EXCLUDING VAT)",
            ),
        ),
    ),
    "newham": (
        Layout(
            name="",
            # 26 files from 2018 and 2019 call the date `Date Incurred`.
            payment_date=("Transaction Date", "Date Incurred"),
            supplier=("BENEFICIARY",),
            directorate=("Local Authority Department", "Directorate"),
            purpose=("Purpose", "Purpose of Expenditure"),
            amount_gbp=("Amount", "Amount (excluding VAT)"),
            vat_gbp=("Non Recoverable", "Non Recoverable VAT"),
        ),
    ),
    "redbridge": (
        Layout(
            name="",
            payment_date=("Transaction Date",),
            supplier=("Supplier description",),
            directorate=("Directorate",),
            department=("Service",),
            purpose=("Account description",),
            amount_gbp=("Amount",),
            reference=("Transaction No",),
        ),
    ),
    "richmond": (
        Layout(
            name="",
            payment_date=("PAYMENT DATE",),
            supplier=("PAYEE",),
            directorate=("DIRECTORATE",),
            purpose=("ACTIVITY",),
            amount_gbp=("PAYMENT AMOUNT",),
        ),
    ),
    "wandsworth": (
        Layout(
            name="",
            payment_date=("PAYMENT DATE",),
            supplier=("PAYEE",),
            directorate=("DIRECTORATE",),
            purpose=("ACTIVITY", "ACTIVTY"),  # two months carry the typo
            amount_gbp=("PAYMENT AMOUNT",),
        ),
    ),
    "westminster": (
        Layout(
            name="",
            payment_date=("Posting date",),
            supplier=("FINAL Supplier name", "Supplier name"),
            directorate=("Department",),
            purpose=("Expense type",),
            amount_gbp=("Amount",),
        ),
    ),
}

#: Boroughs the loader knows how to read, in directory order.
SPEND_BOROUGHS = tuple(sorted(LAYOUTS))


#: Extra header text that marks a header row without being a date column.
#: Wandsworth's July 2024 file has no `PAYMENT DATE` at all, so without this
#: its header row would never be found and `_wandsworth_repair` would never
#: get the chance to put the column back.
HEADER_MARKERS: dict[str, tuple[str, ...]] = {"wandsworth": ("PAYMENT AMOUNT",)}


def date_headers(borough: str) -> tuple[str, ...]:
    """Every header that could be the date column for this borough."""
    seen: list[str] = []
    for layout in LAYOUTS.get(borough, ()):
        for candidate in layout.candidates("payment_date"):
            if candidate not in seen:
                seen.append(candidate)
    return tuple(seen)


def header_markers(borough: str) -> tuple[str, ...]:
    """Header text that says "this row is the header row".

    The date columns, because every layout has one, plus the handful of extras
    above. Searching for these is what makes the Bexley and Brent title rows,
    the Lewisham row 3 header and the two Hounslow files with a leaked SQL
    query in front of them all work without a per-file rule.
    """
    extra = tuple(normalise(name) for name in HEADER_MARKERS.get(borough, ()))
    return date_headers(borough) + extra


def _bind(layout: Layout, header: list[str]) -> tuple[dict[str, int], int]:
    """Field to column index for one layout against one header row."""
    positions: dict[str, list[int]] = {}
    for index, cell in enumerate(header):
        positions.setdefault(normalise(cell), []).append(index)
    columns: dict[str, int] = {}
    for name in FIELDS:
        for candidate in layout.candidates(name):
            if candidate in positions:
                columns[name] = positions[candidate][0]
                break
    return columns, len(columns)


def _wandsworth_repair(header: list[str], columns: dict[str, int]) -> None:
    """Wandsworth 2024-07 heads its date column `PAYMENT AMOUNT` as well.

    The file has six columns and five distinct names: `PAYMENT AMOUNT` appears
    twice and `PAYMENT DATE` not at all, while the data underneath is
    unchanged, dates in the first of the pair and money in the second. Narrow
    on purpose: it fires only when the date column is missing and that exact
    duplication is present.
    """
    if "payment_date" in columns:
        return
    amounts = [
        i for i, cell in enumerate(header) if normalise(cell) == "payment amount"
    ]
    if len(amounts) == 2:
        columns["payment_date"] = amounts[0]
        columns["amount_gbp"] = amounts[1]


_REPAIRS = {"wandsworth": _wandsworth_repair}


def resolve(borough: str, header: list[str]) -> Mapping | None:
    """The best-fitting layout for this header, or None when none fits.

    "Fits" means all three of date, supplier and amount are present. Among the
    layouts that fit, the one matching the most columns wins, and a tie goes to
    the one declared first, which is the doc's own order.
    """
    best: Mapping | None = None
    for layout in LAYOUTS.get(borough, ()):
        columns, matched = _bind(layout, header)
        repair = _REPAIRS.get(borough)
        if repair is not None:
            repair(header, columns)
            matched = len(columns)
        if any(name not in columns for name in REQUIRED):
            continue
        if best is None or matched > best.matched:
            best = Mapping(
                borough=borough,
                layout=layout.name,
                columns=columns,
                header=tuple(header),
                matched=matched,
            )
    return best
