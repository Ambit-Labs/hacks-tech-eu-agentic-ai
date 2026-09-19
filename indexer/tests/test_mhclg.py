"""MHCLG: content API resolution, year enumeration, attachment filtering.

The fixtures are cut down from the real responses captured on 2026-09-19: the
same field names, the same filename conventions, two years instead of sixteen.
"""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs import _govuk, mhclg

ASSET = "https://assets.publishing.service.gov.uk/media"

REVENUE_COLLECTION = {
    "links": {
        "documents": [
            {
                "base_path": "/statistics/rev-2026-to-2027-budget-individual-local-authority-data",
                "title": "Revenue: 2026 to 2027 budget individual local authority data",
            },
            {
                "base_path": "/statistics/rev-2025-to-2026-budget-individual-local-authority-data",
                "title": "Revenue: 2025 to 2026 budget individual local authority data",
            },
            # Same slug shape, outturn rather than budget. Only the title says so.
            {
                "base_path": "/statistics/rev-2024-to-2025-individual-local-authority-data",
                "title": "Revenue: 2024 to 2025 individual local authority data - outturn",
            },
            # A summary release: no per-authority data, and no year pair either.
            {"base_path": "/statistics/rev-first-release", "title": "First release"},
        ]
    }
}

RA_2026 = {
    "title": "Revenue 2026 to 2027 budget",
    "details": {
        "attachments": [
            {
                "title": "RA budget part 1",
                "url": f"{ASSET}/aaa/RA_2026-27_data_Part_1.ods",
            },
            {
                "title": "RA budget part 2",
                "url": f"{ASSET}/bbb/RA_2026-27_data_Part_2.ods",
            },
            {
                "title": "Specific and special revenue grants",
                "url": f"{ASSET}/ccc/SG_2026-27.ods",
            },
            # Not data: a statistical release PDF and an HTML guidance page.
            {"title": "Statistical release", "url": f"{ASSET}/ddd/Release_2026-27.pdf"},
            {"title": "Technical notes", "url": "/statistics/rev-2026/technical-notes"},
        ]
    },
}

RA_2025 = {
    "title": "Revenue 2025 to 2026 budget",
    "details": {
        "attachments": [
            # The pre-2016 shape: the filename is a numeric id and only the
            # attachment title says which return it is.
            {
                "title": "Revenue Account (RA) Budget 2025-26",
                "url": f"{ASSET}/eee/1934015.xls",
            },
        ]
    },
}

EMPTY_RELEASE = {"title": "Nothing here", "details": {"attachments": []}}


def _json(payload):
    return httpx.Response(200, json=payload)


def collection_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/content")
    if path == mhclg.REVENUE_COLLECTION:
        return _json(REVENUE_COLLECTION)
    if path.endswith("2026-to-2027-budget-individual-local-authority-data"):
        return _json(RA_2026)
    if path.endswith("2025-to-2026-budget-individual-local-authority-data"):
        return _json(RA_2025)
    return _json(EMPTY_RELEASE)


@pytest.fixture
def source():
    return mhclg.MHCLG()


def test_a_release_keeps_only_real_files(client_for):
    """An HTML guidance page is served as an attachment with a relative URL."""
    client = client_for(collection_handler)
    release = _govuk.release(
        client, "/statistics/rev-2026-to-2027-budget-individual-local-authority-data"
    )
    assert [a.filename for a in release.attachments] == [
        "RA_2026-27_data_Part_1.ods",
        "RA_2026-27_data_Part_2.ods",
        "SG_2026-27.ods",
        "Release_2026-27.pdf",
    ]


def test_attachment_filtering_drops_the_statistical_release(client_for, source):
    client = client_for(collection_handler)
    found = source._revenue_account(client, None, None)
    names = sorted(f.filename for f in found)
    assert names == [
        "RA_2026-27_data_Part_1.ods",
        "RA_2026-27_data_Part_2.ods",
        "ra-1934015.xls",
        "ra-SG_2026-27.ods",
    ]


def test_year_enumeration_skips_outturn_and_unyeared_releases(client_for, source):
    """The budget and outturn releases share a slug shape; the title parts them."""
    client = client_for(collection_handler)
    periods = {f.period for f in source._revenue_account(client, None, None)}
    assert periods == {"2026-04_2027-03", "2025-04_2026-03"}


def test_a_title_only_match_still_resolves_the_file(client_for, source):
    """Before 2016 the files were called 1934015.xls and nothing else."""
    client = client_for(collection_handler)
    found = {f.filename: f for f in source._revenue_account(client, None, None)}
    old = found["ra-1934015.xls"]
    assert old.period == "2025-04_2026-03"
    assert old.url.endswith("/1934015.xls")
    assert old.format == "xlsx"


def test_since_and_until_prune_before_the_release_is_fetched(client_for, source):
    """A narrow window must not pay a request per year it does not want."""
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(request.url.path)
        return collection_handler(request)

    client = client_for(handler)
    found = source._revenue_account(client, "2026-04", None)
    assert [f.period for f in found] == ["2026-04_2027-03"] * 3
    assert not any("2025-to-2026" in path for path in fetched)


def test_an_empty_release_is_logged_rather_than_silently_skipped(
    client_for, source, caplog
):
    """A renamed file looks exactly like this, and must be visible."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(mhclg.REVENUE_COLLECTION):
            return _json(REVENUE_COLLECTION)
        return _json(EMPTY_RELEASE)

    client = client_for(handler)
    with caplog.at_level("WARNING"):
        assert source._revenue_account(client, None, None) == []
    assert "no ra files matched" in caplog.text


def test_one_broken_family_does_not_cost_the_others(client_for, source, caplog):
    """The council tax collection being moved must not lose the RA budgets."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/content")
        if path == mhclg.REVENUE_COLLECTION:
            return _json(REVENUE_COLLECTION)
        if path.endswith("budget-individual-local-authority-data"):
            return _json(RA_2026 if "2026" in path else RA_2025)
        return httpx.Response(404)

    client = client_for(handler)
    with caplog.at_level("WARNING"):
        found = source.discover(client, None, None)
    assert {f.filename for f in found} >= {"RA_2026-27_data_Part_1.ods"}
    assert "council_tax failed" in caplog.text


def test_the_family_prefix_only_lands_where_it_is_needed():
    assert (
        mhclg._named("ra", "RA_2026-27_data_Part_1.ods") == "RA_2026-27_data_Part_1.ods"
    )
    assert mhclg._named("ra", "SG_2026-27.ods") == "ra-SG_2026-27.ods"
    assert mhclg._named("cor", "COR_A1.ods") == "COR_A1.ods"
    assert mhclg._named("counciltax", "Table_10_2026-27.ods") == (
        "counciltax-Table_10_2026-27.ods"
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "/statistics/rev-england-2026-to-2027-budget-individual-local-authority-data",
            (2026, 2027),
        ),
        (
            "/statistics/rev-england-2010-to-2011-individual-local-authority-data--6",
            (2010, 2011),
        ),
        (
            "/statistics/council-tax-levels-set-by-local-authorities-in-england-2012-to-2013-revised",
            (2012, 2013),
        ),
        # Not a financial year: two calendar years apart.
        ("/statistics/settlement-2026-to-2028", None),
        ("/statistics/rev-first-release", None),
    ],
)
def test_path_years(path, expected):
    assert _govuk.path_years(path) == expected
