"""Barnet: package discovery from the catalogue, and the months inside them."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs.barnet import (
    KNOWN_PACKAGES,
    Barnet,
    resource_period,
)

#: Trimmed ``package_search`` response. The three non-spending packages are
#: real: Barnet publishes agency, Comensura and schools expenditure under
#: titles a keyword search cannot tell from the one we want.
CATALOGUE = {
    "success": True,
    "result": {
        "count": 5,
        "result": [
            {"id": "2ywz8", "title": "Expenditure Reporting 2026/27"},
            {"id": "e6p4n", "title": "Expenditure Reporting 2025/26"},
            {"id": "epz7r", "title": " 2026-27 Agency Expenditure"},
            {"id": "2kd3e", "title": "2017-18 Comensura Expenditure "},
            {"id": "296y2", "title": "Barnet Schools income and expenditure"},
        ],
    },
}

PACKAGES = {
    "2ywz8": [
        {
            "id": "f1f",
            "name": "Expenditure Report July 2026.csv",
            "size": 3744641,
            "url": "https://open.barnet.gov.uk/download/2ywz8/f1f/Expenditure%20Report%20July%202026.csv",
        },
        {
            "id": "7q2",
            "name": "Expenditure Report April 2026.csv",
            "size": 3189875,
            "url": "https://open.barnet.gov.uk/download/2ywz8/7q2/Expenditure%20Report%20April%202026.csv",
        },
    ],
    "e6p4n": [
        {
            "id": "1mj",
            "name": "Expenditure Report March 2026.csv",
            "url": "https://open.barnet.gov.uk/download/e6p4n/1mj/Expenditure%20Report%20March%202026.csv",
        },
    ],
    # 2014/15 keeps a cumulative roll-up of its own twelve months and the
    # below-threshold remainder next to the monthly files.
    "em7ge": [
        {
            "id": "k53",
            "name": "Expenditure over £500 - April 2014",
            "url": "https://open.barnet.gov.uk/download/em7ge/k53/expenditureover500april20141.csv",
        },
        {
            "id": "0pm",
            "name": "Expenditure reporting 2014-15",
            "url": "https://open.barnet.gov.uk/download/em7ge/0pm/Expenditure%20Reporting%202014-15.csv",
        },
        {
            "id": "zjt",
            "name": "1415 Expenditure below 500 & 250",
            "url": "https://open.barnet.gov.uk/download/em7ge/zjt/1415%20Expenditure%20below%20500%20%26%20250.csv",
        },
    ],
    # 2013/14 is one file for the whole financial year and nothing else.
    "20q1e": [
        {
            "id": "y44",
            "name": "Expenditure over £500 - 2013-2014",
            "url": "https://open.barnet.gov.uk/download/20q1e/y44/expenditure-over-500-201314.csv",
        },
    ],
}


def portal(catalogue=CATALOGUE, packages=PACKAGES):
    """A handler for the two endpoints Barnet discovery touches."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("package_search"):
            if catalogue is None:
                return httpx.Response(404, text="not here any more")
            return httpx.Response(200, json=catalogue)
        package_id = request.url.params.get("id")
        if package_id not in packages:
            return httpx.Response(404)
        return httpx.Response(
            200, json={"success": True, "result": {"resources": packages[package_id]}}
        )

    return handler


@pytest.mark.parametrize(
    ("name", "period"),
    [
        ("Expenditure Report July 2026.csv", "2026-07"),
        ("Expenditure Report March 2025 V2.csv", "2025-03"),
        ("Expenditure over £250 - September 2014", "2014-09"),
        ("Expenditure Report Oct 2019.csv", "2019-10"),
        ("Expenditure Report FEBRUARY 2018", "2018-02"),
        # Barnet's own typo for January 2023. Three letters are enough.
        ("Expenditure Report Janurary 2023.csv", "2023-01"),
        # Neither of these is a month, and neither may be guessed into one.
        ("Expenditure reporting 2014-15", None),
        ("1415 Expenditure below 500 & 250", None),
    ],
)
def test_resource_period_reads_the_month_barnet_wrote(name, period):
    assert resource_period(name) == period


def test_discover_finds_only_the_spending_packages(client_for):
    """Agency, Comensura and schools spend share the word and not the dataset."""
    client = client_for(portal())
    periods = {f.period for f in Barnet().discover(client, "2026-03", None)}
    assert periods == {"2026-03", "2026-04", "2026-07"}


def test_files_keep_the_publishers_filename_and_period(client_for):
    client = client_for(portal())
    files = {f.period: f for f in Barnet().discover(client, "2026-07", "2026-07")}
    july = files["2026-07"]
    assert july.filename == "Expenditure Report July 2026.csv"
    assert july.format == "csv"
    assert july.borough == "barnet"
    assert july.url.endswith("Expenditure%20Report%20July%202026.csv")
    # Barnet reissues a month as a new resource at a new URL rather than
    # rewriting one in place, so nothing here is mutable.
    assert july.mutable is False


def test_the_roll_up_and_the_below_threshold_file_are_left_alone(client_for):
    """2014/15 has three resources and one month in it."""
    client = client_for(portal())
    files = Barnet().discover(client, "2014-04", "2014-04")
    assert [f.period for f in files] == ["2014-04"]
    assert "april2014" in files[0].filename


def test_a_year_published_as_one_file_takes_the_whole_year(client_for):
    """2013/14 exists only as a whole-year file, so its period is those months."""
    client = client_for(portal())
    files = Barnet().discover(client, "2013-04", "2013-04")
    assert [f.period for f in files] == ["2013-04_2014-03"]
    assert files[0].title.endswith("(FY 2013-14)")
    # Any month of that financial year reaches it, not only the first.
    inside = Barnet().discover(client_for(portal()), "2014-01", "2014-01")
    assert [f.period for f in inside] == ["2013-04_2014-03"]


def test_since_and_until_skip_whole_financial_years(client_for):
    """A year whose twelve months fall outside the window is never requested."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("package_search"):
            asked.append(request.url.params.get("id"))
        return portal()(request)

    client = client_for(handler)
    files = Barnet().discover(client, "2026-04", None)
    assert [f.period for f in files] == ["2026-07", "2026-04"]
    assert asked == ["2ywz8"]


def test_a_dead_catalogue_falls_back_to_the_known_ids(client_for):
    """The portal being down costs the newest year, not all fourteen."""
    client = client_for(portal(catalogue=None))
    assert Barnet().packages(client) == KNOWN_PACKAGES


def test_a_dead_package_costs_its_own_year_only(client_for):
    """A stale id in the fallback map must not take the other years down."""
    client = client_for(
        portal(packages={k: v for k, v in PACKAGES.items() if k != "e6p4n"})
    )
    periods = [f.period for f in Barnet().discover(client, "2026-03", None)]
    assert periods == ["2026-07", "2026-04"]
