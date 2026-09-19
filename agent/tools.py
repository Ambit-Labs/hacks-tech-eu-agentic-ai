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
        slugs = [slug for b in boroughs if (slug := _slug(b))]
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
    if supplier_like:
        clauses.append("supplier_norm LIKE %(supplier_like)s")
        params["supplier_like"] = _like(_norm(supplier_like))
    if min_amount is not None:
        clauses.append("amount_gbp >= %(min_amount)s")
        params["min_amount"] = min_amount
    if text:
        clauses.append(
            "(supplier_norm LIKE %(text_norm)s OR upper(purpose) LIKE upper(%(text)s)"
            f" OR {DEPARTMENT_EXPR} LIKE upper(%(text)s))"
        )
        params["text_norm"] = _like(_norm(text))
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


# Issue #4 adds spend_by, supplier_payments, largest_payments, search_payments
# and compare_boroughs here, taking this list to seven.
ALL_TOOLS = [coverage, spend_total]
