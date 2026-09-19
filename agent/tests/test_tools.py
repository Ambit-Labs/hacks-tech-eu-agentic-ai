from datetime import date

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from db import Database
from tools import Deps, coverage, spend_total


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
