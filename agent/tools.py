"""The tools the agent can call. Each one is a fixed query over `payments`.

The model never writes SQL. Every tool takes typed arguments, runs one
parameterised statement as the read-only role, and returns a typed result
with the aggregate, the row count behind it, which distinct values a
substring filter matched, and at most ROW_LIMIT rows. Docstrings are what the
model reads when choosing a tool, so they say what the tool answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from db import Database

ROW_LIMIT = 50
MATCH_LIMIT = 20

# The normalisation Postgres applies in the generated column
# payments.supplier_norm, so a supplier filter compares like with like. _norm
# also trims the ends, which the stored column does not; inside a substring
# pattern that makes no difference.
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

# The expression the department trigram index is built on, verbatim from
# docs/payments-schema.sql.
DEPARTMENT_EXPR = "upper(coalesce(directorate, '') || ' ' || coalesce(department, ''))"
DEPARTMENT_LABEL = "coalesce(directorate, '') || ' / ' || coalesce(department, '')"

GroupBy = Literal["department", "purpose", "supplier", "month", "financial_year"]

GROUP_EXPR: dict[str, str] = {
    "department": DEPARTMENT_LABEL,
    "purpose": "coalesce(purpose, '')",
    "supplier": "supplier",
    "month": "to_char(date_trunc('month', payment_date), 'YYYY-MM')",
    "financial_year": "financial_year",
}


@dataclass
class Deps:
    db: Database


class Matched(BaseModel):
    """Which distinct values a substring filter matched, so the answer can name them."""

    departments: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)


class CoverageRow(BaseModel):
    borough: str
    month: date
    payments: int
    total_gbp: float


class Coverage(BaseModel):
    rows: list[CoverageRow]


class SpendTotal(BaseModel):
    borough: str
    period_from: date
    period_to: date
    total_gbp: float
    payments: int
    matched: Matched


class GroupRow(BaseModel):
    key: str
    total_gbp: float
    payments: int


class SpendBy(BaseModel):
    borough: str
    period_from: date
    period_to: date
    group_by: str
    rows: list[GroupRow]
    matched: Matched


def _slug(borough: str) -> str:
    return borough.strip().lower()


def _like(value: str) -> str:
    """A LIKE pattern that matches `value` as a substring, wildcards escaped."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _norm(value: str) -> str:
    return _NON_ALNUM.sub(" ", value.upper()).strip()


def _clamp(limit: int, ceiling: int = ROW_LIMIT) -> int:
    return max(1, min(limit, ceiling))


def _filters(
    *,
    period_from: date,
    period_to: date,
    borough: str | None = None,
    boroughs: list[str] | None = None,
    department_like: str | None = None,
    purpose_like: str | None = None,
    supplier_like: str | None = None,
    min_amount: float | None = None,
    text: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """A WHERE clause body and its parameters. Only the filters given are added."""
    clauses = ["payment_date >= %(period_from)s", "payment_date <= %(period_to)s"]
    params: dict[str, Any] = {"period_from": period_from, "period_to": period_to}
    # None means every borough. A blank string is the model sending nothing
    # where a borough was required, which must not silently widen the query.
    if borough is not None:
        slug = _slug(borough)
        if not slug:
            raise ModelRetry("borough must be a borough slug such as camden")
        clauses.append("borough = %(borough)s")
        params["borough"] = slug
    if boroughs is not None:
        # dict.fromkeys keeps the first occurrence of each slug, so asking for
        # the same borough twice compares it once instead of doubling it.
        slugs = list(dict.fromkeys(slug for b in boroughs if (slug := _slug(b))))
        if not slugs:
            raise ModelRetry("boroughs must list at least one borough slug")
        clauses.append("borough = ANY(%(boroughs)s)")
        params["boroughs"] = slugs
    if department_like:
        clauses.append(f"{DEPARTMENT_EXPR} LIKE upper(%(department_like)s)")
        # The separator collapses so a label from Matched.departments, which
        # reads "Children / Social Work", can be passed straight back.
        params["department_like"] = _like(department_like.replace(" / ", " "))
    if purpose_like:
        clauses.append("upper(purpose) LIKE upper(%(purpose_like)s)")
        params["purpose_like"] = _like(purpose_like)
    if supplier_like is not None:
        # _norm drops every non-alphanumeric run, so punctuation on its own
        # would leave the pattern '%%', which matches every payment ever made.
        normalised = _norm(supplier_like)
        if not normalised:
            raise ModelRetry("supplier_like needs at least one letter or digit")
        clauses.append("supplier_norm LIKE %(supplier_like)s")
        params["supplier_like"] = _like(normalised)
    if min_amount is not None:
        clauses.append("amount_gbp >= %(min_amount)s")
        params["min_amount"] = min_amount
    if text is not None:
        # Same trap as supplier_like: the supplier half of this OR would match
        # everything if the search text normalised away to nothing.
        normalised = _norm(text)
        if not normalised:
            raise ModelRetry("text needs at least one letter or digit to search for")
        clauses.append(
            "(supplier_norm LIKE %(text_norm)s OR upper(purpose) LIKE upper(%(text)s)"
            f" OR {DEPARTMENT_EXPR} LIKE upper(%(text)s))"
        )
        params["text_norm"] = _like(normalised)
        params["text"] = _like(text)
    return " AND ".join(clauses), params


async def _matched(
    db: Database, where: str, params: dict[str, Any], *, department: bool, purpose: bool
) -> Matched:
    """The distinct department and purpose values inside a filtered set."""
    result = Matched()
    if department:
        rows = await db.fetch_all(
            f"SELECT DISTINCT {DEPARTMENT_LABEL} AS label FROM payments WHERE {where}"
            f" ORDER BY label LIMIT {MATCH_LIMIT}",
            params,
        )
        result.departments = [r["label"] for r in rows]
    if purpose:
        rows = await db.fetch_all(
            f"SELECT DISTINCT coalesce(purpose, '') AS label FROM payments WHERE {where}"
            f" ORDER BY label LIMIT {MATCH_LIMIT}",
            params,
        )
        result.purposes = [r["label"] for r in rows]
    return result


async def coverage(ctx: RunContext[Deps], borough: str | None = None) -> Coverage:
    """Which boroughs have data and which months each covers, with payment counts and totals. Use it when unsure whether a borough or period is loaded."""
    where = "WHERE borough = %(borough)s" if borough else ""
    rows = await ctx.deps.db.fetch_all(
        f"SELECT borough, month, payments, total_gbp FROM coverage {where} ORDER BY borough, month",
        {"borough": _slug(borough)} if borough else None,
    )
    return Coverage(
        rows=[
            CoverageRow(
                borough=r["borough"],
                month=r["month"],
                payments=r["payments"],
                total_gbp=float(r["total_gbp"]),
            )
            for r in rows
        ]
    )


async def spend_total(
    ctx: RunContext[Deps],
    borough: str,
    period_from: date,
    period_to: date,
    department_like: str | None = None,
    purpose_like: str | None = None,
) -> SpendTotal:
    """Total spend of one borough between two dates, inclusive, with the number of payments behind it. Narrow it with a substring of the department or of the purpose, such as "temporary accommodation" or "agency"."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        borough=borough,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    rows = await ctx.deps.db.fetch_all(
        f"SELECT coalesce(sum(amount_gbp), 0) AS total, count(*) AS n FROM payments WHERE {where}",
        params,
    )
    matched = await _matched(
        ctx.deps.db, where, params, department=bool(department_like), purpose=bool(purpose_like)
    )
    return SpendTotal(
        borough=_slug(borough),
        period_from=period_from,
        period_to=period_to,
        total_gbp=float(rows[0]["total"]),
        payments=rows[0]["n"],
        matched=matched,
    )


async def spend_by(
    ctx: RunContext[Deps],
    borough: str,
    period_from: date,
    period_to: date,
    group_by: GroupBy,
    department_like: str | None = None,
    purpose_like: str | None = None,
    limit: int = 20,
) -> SpendBy:
    """Spend of one borough between two dates broken down by department, purpose, supplier, month or financial year. Biggest first, except month and financial_year which come in date order. Use it for top suppliers, which department spends most, and trends over time."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        borough=borough,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    expr = GROUP_EXPR[group_by]
    order = "key" if group_by in ("month", "financial_year") else "total DESC, key"
    rows = await ctx.deps.db.fetch_all(
        f"SELECT {expr} AS key, sum(amount_gbp) AS total, count(*) AS n FROM payments"
        f" WHERE {where} GROUP BY key ORDER BY {order} LIMIT {_clamp(limit)}",
        params,
    )
    matched = await _matched(
        ctx.deps.db, where, params, department=bool(department_like), purpose=bool(purpose_like)
    )
    return SpendBy(
        borough=_slug(borough),
        period_from=period_from,
        period_to=period_to,
        group_by=group_by,
        rows=[GroupRow(key=r["key"], total_gbp=float(r["total"]), payments=r["n"]) for r in rows],
        matched=matched,
    )


PAYMENT_COLUMNS = (
    "borough, payment_date, supplier, directorate, department, purpose, amount_gbp, reference"
)


class Payment(BaseModel):
    borough: str
    payment_date: date
    supplier: str
    directorate: str | None
    department: str | None
    purpose: str | None
    amount_gbp: float
    reference: str | None


class Payments(BaseModel):
    """A filtered set of payments: the total and count over the whole set, and at most ROW_LIMIT rows."""

    total_gbp: float
    payments: int
    rows: list[Payment]


class SupplierPayments(BaseModel):
    supplier_like: str
    boroughs: list[str]
    total_gbp: float
    payments: int
    first_date: date | None
    last_date: date | None
    rows: list[Payment]


class ComparisonRow(BaseModel):
    borough: str
    total_gbp: float
    payments: int
    population: int | None
    gbp_per_resident: float | None


class BoroughComparison(BaseModel):
    period_from: date
    period_to: date
    rows: list[ComparisonRow]
    matched: Matched


def _payment(r: dict[str, Any]) -> Payment:
    return Payment(
        borough=r["borough"],
        payment_date=r["payment_date"],
        supplier=r["supplier"],
        directorate=r["directorate"],
        department=r["department"],
        purpose=r["purpose"],
        amount_gbp=float(r["amount_gbp"]),
        reference=r["reference"],
    )


async def _payment_set(db: Database, where: str, params: dict[str, Any], *, order: str, limit: int) -> Payments:
    totals = await db.fetch_all(
        f"SELECT coalesce(sum(amount_gbp), 0) AS total, count(*) AS n FROM payments WHERE {where}",
        params,
    )
    rows = await db.fetch_all(
        f"SELECT {PAYMENT_COLUMNS} FROM payments WHERE {where} ORDER BY {order} LIMIT {_clamp(limit)}",
        params,
    )
    return Payments(
        total_gbp=float(totals[0]["total"]),
        payments=totals[0]["n"],
        rows=[_payment(r) for r in rows],
    )


async def supplier_payments(
    ctx: RunContext[Deps],
    supplier_like: str,
    period_from: date,
    period_to: date,
    borough: str | None = None,
) -> SupplierPayments:
    """Everything paid to suppliers whose name contains the given text, ignoring case and punctuation, between two dates: total, count, first and last payment date, which boroughs paid them, and the payments. Leave borough empty to search every borough."""
    where, params = _filters(
        period_from=period_from, period_to=period_to, borough=borough, supplier_like=supplier_like
    )
    summary = await ctx.deps.db.fetch_all(
        "SELECT coalesce(sum(amount_gbp), 0) AS total, count(*) AS n,"
        " min(payment_date) AS first_date, max(payment_date) AS last_date,"
        " array_remove(array_agg(DISTINCT borough), NULL) AS boroughs"
        f" FROM payments WHERE {where}",
        params,
    )
    rows = await ctx.deps.db.fetch_all(
        f"SELECT {PAYMENT_COLUMNS} FROM payments WHERE {where}"
        f" ORDER BY payment_date DESC, amount_gbp DESC, id LIMIT {ROW_LIMIT}",
        params,
    )
    s = summary[0]
    return SupplierPayments(
        supplier_like=supplier_like,
        boroughs=sorted(s["boroughs"] or []),
        total_gbp=float(s["total"]),
        payments=s["n"],
        first_date=s["first_date"],
        last_date=s["last_date"],
        rows=[_payment(r) for r in rows],
    )


async def largest_payments(
    ctx: RunContext[Deps],
    period_from: date,
    period_to: date,
    borough: str | None = None,
    limit: int = 20,
    min_amount: float | None = None,
    department_like: str | None = None,
    purpose_like: str | None = None,
) -> Payments:
    """The biggest single payments between two dates, largest first, in one borough or across all of them. Narrow with a minimum amount or a substring of the department or purpose. total_gbp and payments cover every matching payment, not only the rows returned."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        borough=borough,
        min_amount=min_amount,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    return await _payment_set(
        ctx.deps.db, where, params, order="amount_gbp DESC, payment_date DESC, id", limit=limit
    )


async def search_payments(
    ctx: RunContext[Deps],
    text: str,
    period_from: date,
    period_to: date,
    borough: str | None = None,
    min_amount: float | None = None,
    limit: int = 50,
) -> Payments:
    """Payments whose supplier, purpose or department contains the given text, between two dates. Use it for "show me the payments for" questions about a topic such as parks, roads, libraries or consultants. total_gbp and payments cover every matching payment, not only the rows returned."""
    where, params = _filters(
        period_from=period_from, period_to=period_to, borough=borough, min_amount=min_amount, text=text
    )
    return await _payment_set(
        ctx.deps.db, where, params, order="payment_date DESC, amount_gbp DESC, id", limit=limit
    )


async def compare_boroughs(
    ctx: RunContext[Deps],
    boroughs: list[str],
    period_from: date,
    period_to: date,
    department_like: str | None = None,
    purpose_like: str | None = None,
) -> BoroughComparison:
    """Total spend of several boroughs over the same period side by side, with spend per resident where the population is known. Narrow with a substring of the department or purpose to compare one kind of spend."""
    where, params = _filters(
        period_from=period_from,
        period_to=period_to,
        boroughs=boroughs,
        department_like=department_like,
        purpose_like=purpose_like,
    )
    # The borough comes from the asked-for slug, not from `boroughs`, so a
    # borough with no row there still comes back, with a NULL population.
    rows = await ctx.deps.db.fetch_all(
        "SELECT asked.slug AS borough, b.population,"
        " coalesce(sum(p.amount_gbp), 0) AS total, count(p.id) AS n"
        " FROM unnest(%(boroughs)s::text[]) AS asked(slug)"
        " LEFT JOIN boroughs b ON b.slug = asked.slug"
        f" LEFT JOIN payments p ON p.borough = asked.slug AND ({where})"
        " GROUP BY asked.slug, b.population ORDER BY total DESC",
        params,
    )
    matched = await _matched(
        ctx.deps.db, where, params, department=bool(department_like), purpose=bool(purpose_like)
    )
    out: list[ComparisonRow] = []
    for r in rows:
        total = float(r["total"])
        population = r["population"]
        out.append(
            ComparisonRow(
                borough=r["borough"],
                total_gbp=total,
                payments=r["n"],
                population=population,
                gbp_per_resident=(total / population) if population else None,
            )
        )
    return BoroughComparison(period_from=period_from, period_to=period_to, rows=out, matched=matched)


ALL_TOOLS = [
    coverage,
    spend_total,
    spend_by,
    supplier_payments,
    largest_payments,
    search_payments,
    compare_boroughs,
]
