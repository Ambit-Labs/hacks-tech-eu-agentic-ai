from datetime import date

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from db import Database
from tools import Deps, coverage, spend_by, spend_total


@pytest.fixture
async def ctx(database_url):
    db = Database(database_url)
    await db.open()
    yield RunContext(deps=Deps(db=db), model=TestModel(), usage=RunUsage())
    await db.close()


async def test_coverage_lists_every_borough_and_month(ctx):
    result = await coverage(ctx)
    got = {(r.borough, r.month.isoformat(), r.payments, r.total_gbp) for r in result.rows}
    assert got == {
        ("camden", "2019-09-01", 6, 10000.0),
        ("camden", "2019-10-01", 4, 4000.0),
        ("islington", "2019-09-01", 5, 6000.0),
        ("islington", "2019-10-01", 3, 2100.0),
    }


async def test_coverage_for_one_borough(ctx):
    result = await coverage(ctx, borough="Islington ")
    assert {r.borough for r in result.rows} == {"islington"}


async def test_spend_total_for_a_month(ctx):
    result = await spend_total(ctx, "camden", date(2019, 9, 1), date(2019, 9, 30))
    assert result.total_gbp == 10000.0
    assert result.payments == 6
    assert result.matched.departments == []


async def test_spend_total_with_purpose_filter_reports_matches(ctx):
    result = await spend_total(
        ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), purpose_like="temporary accom"
    )
    assert result.total_gbp == 1400.0
    assert result.payments == 2
    assert result.matched.purposes == ["Temporary Accommodation"]


async def test_spend_total_with_department_filter(ctx):
    result = await spend_total(
        ctx, "islington", date(2019, 9, 1), date(2019, 10, 31), department_like="social work"
    )
    assert result.total_gbp == 2200.0
    assert result.matched.departments == ["Children / Social Work"]


async def test_spend_total_takes_a_matched_label_back(ctx):
    result = await spend_total(
        ctx,
        "islington",
        date(2019, 9, 1),
        date(2019, 10, 31),
        department_like="Children / Social Work",
    )
    assert result.total_gbp == 2200.0
    assert result.payments == 2


async def test_spend_total_rejects_a_blank_borough(ctx):
    with pytest.raises(ModelRetry):
        await spend_total(ctx, "", date(2019, 9, 1), date(2019, 9, 30))


async def test_spend_total_empty(ctx):
    result = await spend_total(ctx, "hackney", date(2019, 9, 1), date(2019, 9, 30))
    assert result.total_gbp == 0.0
    assert result.payments == 0


async def test_spend_total_escapes_like_wildcards(ctx):
    result = await spend_total(ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), purpose_like="%")
    assert result.payments == 0


async def test_spend_by_supplier_orders_by_total(ctx):
    result = await spend_by(ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), group_by="supplier")
    assert [(r.key, r.total_gbp, r.payments) for r in result.rows[:2]] == [
        ("NSL LIMITED", 5600.0, 4),
        ("CAPITA BUSINESS SERVICES", 5000.0, 2),
    ]


async def test_spend_by_month_orders_by_key(ctx):
    result = await spend_by(ctx, "islington", date(2019, 9, 1), date(2019, 10, 31), group_by="month")
    assert [(r.key, r.total_gbp) for r in result.rows] == [("2019-09", 6000.0), ("2019-10", 2100.0)]


async def test_spend_by_department_joins_both_levels(ctx):
    result = await spend_by(ctx, "islington", date(2019, 9, 1), date(2019, 9, 30), group_by="department")
    assert result.rows[0].key == "Housing / Cap Prog Delivery"
    assert result.rows[0].total_gbp == 3100.0


async def test_spend_by_limit_is_clamped(ctx):
    result = await spend_by(ctx, "camden", date(2019, 9, 1), date(2019, 10, 31), group_by="supplier", limit=0)
    assert len(result.rows) == 1


from tools import ALL_TOOLS, compare_boroughs, largest_payments, search_payments, supplier_payments


async def test_supplier_payments_matches_across_case_and_suffix(ctx):
    result = await supplier_payments(ctx, "capita", date(2019, 9, 1), date(2019, 10, 31))
    # Two payments per borough, matched across case and the Ltd suffix.
    assert result.total_gbp == 8000.0
    assert result.payments == 4
    assert result.boroughs == ["camden", "islington"]
    assert result.first_date == date(2019, 9, 3)
    assert result.last_date == date(2019, 10, 11)
    assert len(result.rows) == 4


async def test_supplier_payments_in_one_borough(ctx):
    result = await supplier_payments(ctx, "NSL", date(2019, 9, 1), date(2019, 10, 31), borough="camden")
    assert result.total_gbp == 5600.0
    assert result.payments == 4


async def test_supplier_payments_none(ctx):
    result = await supplier_payments(ctx, "nobody", date(2019, 9, 1), date(2019, 10, 31))
    assert result.payments == 0
    assert result.first_date is None
    assert result.rows == []


async def test_largest_payments_across_boroughs(ctx):
    result = await largest_payments(ctx, date(2019, 9, 1), date(2019, 10, 31), limit=3)
    assert [(r.borough, r.amount_gbp) for r in result.rows] == [
        ("camden", 5000.0),
        ("camden", 3000.0),
        ("islington", 2500.0),
    ]
    # payments counts the whole period, not the three rows the limit returned.
    assert result.payments == 18


async def test_largest_payments_with_min_amount_and_borough(ctx):
    result = await largest_payments(
        ctx, date(2019, 9, 1), date(2019, 10, 31), borough="islington", min_amount=1000
    )
    assert [r.amount_gbp for r in result.rows] == [2500.0, 1500.0, 1200.0, 1000.0]


async def test_search_payments_matches_purpose_supplier_or_department(ctx):
    by_purpose = await search_payments(ctx, "construction", date(2019, 9, 1), date(2019, 10, 31))
    assert {r.supplier for r in by_purpose.rows} == {"BIG BUILD CONSTRUCTION LTD", "Big Build Construction Ltd"}

    by_department = await search_payments(ctx, "estates", date(2019, 9, 1), date(2019, 10, 31))
    assert by_department.payments == 2

    by_supplier = await search_payments(ctx, "reed", date(2019, 9, 1), date(2019, 10, 31), borough="islington")
    assert by_supplier.total_gbp == 3700.0


async def test_search_payments_limit(ctx):
    result = await search_payments(ctx, "a", date(2019, 9, 1), date(2019, 10, 31), limit=2)
    assert len(result.rows) == 2
    assert result.payments > 2


async def test_compare_boroughs_totals_and_per_resident(ctx):
    result = await compare_boroughs(ctx, ["camden", "islington"], date(2019, 9, 1), date(2019, 10, 31))
    rows = {r.borough: r for r in result.rows}
    assert rows["camden"].total_gbp == 14000.0
    assert rows["camden"].payments == 10
    assert rows["camden"].population == 210000
    assert rows["camden"].gbp_per_resident == pytest.approx(14000.0 / 210000, rel=1e-6)
    assert rows["islington"].total_gbp == 8100.0


async def test_compare_boroughs_with_purpose_filter(ctx):
    result = await compare_boroughs(
        ctx, ["camden", "islington"], date(2019, 9, 1), date(2019, 10, 31), purpose_like="agency"
    )
    rows = {r.borough: r for r in result.rows}
    assert rows["islington"].total_gbp == 3700.0
    assert rows["camden"].total_gbp == 0.0
    assert result.matched.purposes == ["Agency Staff"]


async def test_compare_boroughs_unknown_borough_has_no_population(ctx):
    result = await compare_boroughs(ctx, ["hackney"], date(2019, 9, 1), date(2019, 10, 31))
    assert result.rows[0].population is None
    assert result.rows[0].gbp_per_resident is None


def test_all_tools_lists_seven():
    assert [t.__name__ for t in ALL_TOOLS] == [
        "coverage", "spend_total", "spend_by", "supplier_payments",
        "largest_payments", "search_payments", "compare_boroughs",
    ]
