"""One file's data rows turned into `payments` tuples, with the rejects counted.

A row that breaks a value rule is dropped and the file still loads, because a
month with nine unparseable dates in it is still ninety-nine per cent of that
month's spending and refusing the whole file would lose all of it. The count
and the reasons go into `source_files.reason`, so a borough whose dates went
bad in 2016 is visible from a single query rather than from reading logs.

`source_row` counts every data row after the header, blanks and drops included,
so a gap in the numbering is the record that something was thrown away.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from psycopg.types.json import Jsonb

from .mappings import Mapping
from .readers import Table
from .values import (
    ValueError_,
    clean_text,
    financial_year,
    parse_amount,
    parse_date,
    parse_optional_amount,
    slash_parts,
)

#: The three answers :func:`detect_date_order` gives.
DAY_FIRST = "day-first"
MONTH_FIRST = "month-first"
MIXED = "mixed"


class AmbiguousDateOrder(Exception):
    """A slash date in this file has no day-first reading.

    One cell cannot say whether the file is month first throughout or has a
    single transposed row in an otherwise day-first column, and the difference
    decides whether the file loads or fails. The runner catches this, scans the
    whole date column with :func:`detect_date_order`, and tries again.
    """


def detect_date_order(table: Table, mapping: Mapping) -> str:
    """Read one file's date column and say which order its slash dates are in.

    A file is read month first only when at least one slash date has a second
    number above 12 and none has a first number above 12. Both kinds present
    means the column contradicts itself and the file is `mixed`, which fails.
    Everything else, including a file where every date is ambiguous, stays
    day first.

    Streams the column and keeps two booleans, so a 20 MB quarter costs one
    more read and no memory.
    """
    date_at = mapping.columns["payment_date"]
    second_over_12 = first_over_12 = False
    for row in table.rows:
        if date_at >= len(row):
            continue
        parts = slash_parts(row[date_at])
        if parts is None:
            continue
        first, second = parts
        second_over_12 |= second > 12
        first_over_12 |= first > 12
        if second_over_12 and first_over_12:
            return MIXED
    if second_over_12 and not first_over_12:
        return MONTH_FIRST
    return DAY_FIRST


@dataclass
class RowStats:
    """Running totals for one file."""

    read: int = 0
    loaded: int = 0
    blank: int = 0
    dropped: dict[str, int] = field(default_factory=dict)

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def reason(self) -> str | None:
        """`12 rows dropped: 9 bad date, 3 empty supplier`, or None when clean."""
        if not self.dropped:
            return None
        parts = ", ".join(
            f"{count} {reason}"
            for reason, count in sorted(self.dropped.items(), key=lambda kv: -kv[1])
        )
        return f"{self.dropped_total} rows dropped: {parts}"


def raw_keys(header: list[str]) -> list[str]:
    """One JSON key per column, headers kept as published where they can be.

    `raw` is a JSON object and a file is not: Barnet pads its rows with up to
    28 unnamed trailing columns and Wandsworth's July 2024 file names two
    columns `PAYMENT AMOUNT`. A nameless column becomes `#7` for its position
    and a repeat becomes `PAYMENT AMOUNT #2`, which keeps every published cell
    without one silently overwriting another.
    """
    keys: list[str] = []
    seen: dict[str, int] = {}
    for index, cell in enumerate(header, start=1):
        name = str(cell or "").strip()
        if not name:
            keys.append(f"#{index}")
            continue
        seen[name] = seen.get(name, 0) + 1
        keys.append(name if seen[name] == 1 else f"{name} #{seen[name]}")
    return keys


def _raw(keys: list[str], row: list[object]) -> dict[str, str]:
    out: dict[str, str] = {}
    for index, cell in enumerate(row):
        key = keys[index] if index < len(keys) else f"#{index + 1}"
        out[key] = "" if cell is None else str(cell)
    return out


def _cell(row: list[object], index: int | None) -> object:
    if index is None or index >= len(row):
        return None
    return row[index]


def payment_rows(
    table: Table,
    mapping: Mapping,
    *,
    borough: str,
    source_file: str,
    stats: RowStats,
    date_order: str = DAY_FIRST,
) -> Iterator[tuple]:
    """Yield one COPY tuple per row that survives the value rules."""
    month_first = date_order == MONTH_FIRST
    keys = raw_keys(table.header)
    columns = mapping.columns
    date_at = columns["payment_date"]
    supplier_at = columns["supplier"]
    amount_at = columns["amount_gbp"]
    directorate_at = columns.get("directorate")
    department_at = columns.get("department")
    purpose_at = columns.get("purpose")
    vat_at = columns.get("vat_gbp")
    reference_at = columns.get("reference")

    for offset, row in enumerate(table.rows, start=1):
        stats.read = offset
        supplier = clean_text(_cell(row, supplier_at))
        amount_cell = _cell(row, amount_at)
        amount_blank = amount_cell is None or str(amount_cell).strip() == ""
        if supplier is None and amount_blank:
            # A fully blank row, or a section marker like Bexley's `APRIL`, or
            # a total line under the last payment. None of them is a payment
            # and none of them is a fault.
            stats.blank += 1
            continue
        try:
            day = parse_date(_cell(row, date_at), month_first=month_first)
        except ValueError_ as exc:
            if exc.reason == "month-first date":
                raise AmbiguousDateOrder(
                    f"no day-first reading at row {offset}"
                ) from exc
            stats.drop(exc.reason)
            continue
        if supplier is None:
            stats.drop("empty supplier")
            continue
        try:
            amount = parse_amount(amount_cell)
        except ValueError_ as exc:
            stats.drop(exc.reason)
            continue
        stats.loaded += 1
        yield (
            borough,
            day,
            financial_year(day),
            supplier,
            clean_text(_cell(row, directorate_at)),
            clean_text(_cell(row, department_at)),
            clean_text(_cell(row, purpose_at)),
            amount,
            parse_optional_amount(_cell(row, vat_at)),
            clean_text(_cell(row, reference_at)),
            source_file,
            offset,
            Jsonb(_raw(keys, row)),
        )
