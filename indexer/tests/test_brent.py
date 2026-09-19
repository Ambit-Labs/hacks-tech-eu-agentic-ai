"""Brent: two quarter cycles, one period grammar, and the names in between."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.boroughs.base import filter_files
from scrooge_indexer.boroughs.brent import Brent, span_period

#: Trimmed ``package_show`` for vq756, one resource from each era: the
#: financial quarters of today, the four-month file that realigned them, an
#: off-cycle December to February quarter, and the one name that puts the year
#: on the last month only.
RESOURCES = [
    {
        "id": "r9z",
        "name": "Transparency Report Apr 2026 - Jun 2026.csv",
        "size": 2393310,
        "url": "https://data.brent.gov.uk/download/vq756/r9z/Transparency%20Report%20Apr%202026%20-%20Jun%202026.csv",
    },
    {
        "id": "3gl",
        "name": "Transparency Report Jan 2026 - Mar 2026.csv",
        "url": "https://data.brent.gov.uk/download/vq756/3gl/Transparency%20Report%20Jan%202026%20-%20Mar%202026.csv",
    },
    {
        "id": "ey3",
        "name": "Transparency Report Dec 2024 - Mar 2025.csv",
        "url": "https://data.brent.gov.uk/download/vq756/ey3/Transparency%20Report%20Dec%202024%20-%20Mar%202025.csv",
    },
    {
        "id": "gmb",
        "name": "Transparency Report Jun 2024 - Aug 2024.csv",
        "url": "https://data.brent.gov.uk/download/vq756/gmb/Transparency%2024%20June%20-%2024%20August.csv",
    },
    {
        "id": "q85",
        "name": "Transparency-report-Mar-May 2020.csv",
        "url": "https://data.brent.gov.uk/download/vq756/q85/transparency-report-mar-may-2020.csv",
    },
]


def package_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.params.get("id") == "vq756"
    return httpx.Response(
        200, json={"success": True, "result": {"resources": RESOURCES}}
    )


@pytest.mark.parametrize(
    ("name", "period"),
    [
        # April to June is Q1 of the financial year that starts that April.
        ("Transparency Report Apr 2026 - Jun 2026.csv", "2026-Q1"),
        # January to March is Q4 of the year that started the previous April,
        # so the label is 2025 even though every month in it is 2026.
        ("Transparency Report Jan 2026 - Mar 2026.csv", "2025-Q4"),
        ("Transparency Report Jul 2025-Sept 2025 revised.csv", "2025-Q2"),
        ("Transparency Report Oct 2025-Dec 2025.csv", "2025-Q3"),
        # Before 2025 the cycle started in March and matched no quarter of
        # either convention, so these keep the months they really cover.
        ("Transparency report Mar 2021-May 2021.csv", "2021-03_2021-05"),
        ("Transparency report Sep 2020-Nov 2020.csv", "2020-09_2020-11"),
        ("Transparency report Dec 2021 - Feb 2022 revised.csv", "2021-12_2022-02"),
        # Four months, to move the cycle onto the financial year.
        ("Transparency Report Dec 2024 - Mar 2025.csv", "2024-12_2025-03"),
        # The en dash is Brent's, not a typo here.
        ("Transparency report Mar 2024 – May 2024.csv", "2024-03_2024-05"),
        # Only the last month carries a year.
        ("Transparency-report-Mar-May 2020.csv", "2020-03_2020-05"),
        ("Transparency Report", None),
    ],
)
def test_span_period_reads_both_cycles(name, period):
    assert span_period(name) == period


def test_two_digit_numbers_in_a_filename_are_not_years():
    """ "Transparency 24 June - 24 August" is the June to August 2024 file.

    The 24 reads as a day here and as a year elsewhere, so Brent asks the
    shared reader for four-digit years and takes the period from the resource
    name, which spells both years out.
    """
    assert span_period("Transparency 24 June - 24 August") is None


def test_discover_reads_the_period_from_the_name_not_the_url(client_for):
    client = client_for(package_handler)
    files = {f.period: f for f in Brent().discover(client, None, None)}
    assert set(files) == {
        "2026-Q1",
        "2025-Q4",
        "2024-12_2025-03",
        "2024-06_2024-08",
        "2020-03_2020-05",
    }
    # The June to August 2024 file is called "Transparency 24 June - 24
    # August.csv" on disk at Brent's end, and the name on the dataset is what
    # says which months it covers.
    assert files["2024-06_2024-08"].filename == "Transparency 24 June - 24 August.csv"


def test_files_carry_the_publishers_filename_and_format(client_for):
    client = client_for(package_handler)
    first = {f.period: f for f in Brent().discover(client, None, None)}["2026-Q1"]
    assert first.filename == "Transparency Report Apr 2026 - Jun 2026.csv"
    assert first.format == "csv"
    assert first.borough == "brent"
    assert first.mutable is False


def test_quarters_are_financial_so_filtering_uses_april(client_for):
    """``2026-Q1`` covers April to June 2026, and the filters must agree."""
    client = client_for(package_handler)
    files = Brent().discover(client, None, None)
    kept = filter_files(files, "2026-06", None, quarters=Brent.quarters)
    assert [f.period for f in kept] == ["2026-Q1"]
    assert filter_files(files, "2026-07", None, quarters=Brent.quarters) == []


def test_the_four_month_file_says_all_four_months(client_for):
    """December 2024 to March 2025 is one file and one period, ``2024-12_2025-03``.

    A window of February 2025 alone reaches it, which under the old
    first-month convention it did not.
    """
    client = client_for(package_handler)
    files = Brent().discover(client, None, None)
    inside = filter_files(files, "2025-02", "2025-02", quarters=Brent.quarters)
    assert [f.period for f in inside] == ["2024-12_2025-03"]
    after = filter_files(files, "2025-04", None, quarters=Brent.quarters)
    assert "2024-12_2025-03" not in [f.period for f in after]
