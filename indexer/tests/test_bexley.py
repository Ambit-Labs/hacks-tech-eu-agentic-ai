"""Bexley: the upload folder is not the period, and the card sections go."""

from __future__ import annotations

import logging

import httpx
import pytest

from spend_indexer.boroughs.bexley import Bexley, expenditure_sections, link_period

#: Trimmed from the live page on 2026-09-19, keeping the heading structure
#: intact: a year heading introduces that year's expenditure files and a
#: "Pcard" heading introduces the purchase card files. The 2017 link is
#: Bexley's own mistake, kept verbatim: it is labelled April to June 2017 and
#: points at a purchase card file for April to December 2018.
LANDING = """
<html><body>
<h4 class="accordion__title">Expenditure records (CSV files)</h4>
<h4>2026</h4><p>
<a href="/sites/default/files/2026-08/july-2026.csv">July 2026 (CSV)</a><br>
<a href="/sites/default/files/2026-08/expenditure-june-2026.csv">June 2026 (CSV)</a><br>
<a href="https://www.bexley.gov.uk/sites/default/files/2026-05/expenditure-march-2026_0.csv">March 2026 (CSV)</a>
</p>
<h4>Pcard</h4><p>
<a href="/sites/default/files/2026-09/pcard-expenditure-august-2026.csv">August 2026 (CSV)</a><br>
<a href="/sites/default/files/2025-12/november-2025.csv">November 2025 (CSV)</a><br>
<a href="/sites/default/files/2025-07/publication_payments_over_June_2025.csv">June 2025 (CSV)</a>
</p>
<h4>2025</h4><p>
<a href="/sites/default/files/2026-01/November-2025-v1.csv">November 2025 (CSV)</a><br>
<a href="/sites/default/files/2025-10/Aug_2025_v1.csv">August 2025 (CSV)</a><br>
<a href="/sites/default/files/2025-02/Dec_24_v3.csv">December 2024 (CS)V</a>
</p>
<h4>2018</h4><p>
<a href="/sites/default/files/2020-05/October-December-2018.csv">October to December (CSV)</a>
</p>
<h4>2017</h4><p>
<a href="/sites/default/files/2020-05/April-to-December-2018-v1.csv">April to June 2017 (CSV)</a>
</p>
<h4>2010</h4><p>
<a href="/sites/default/files/2020-05/November-2010-to-March-2011-CSV-format.csv">November 2010 to March 2011 (CSV)</a>
</p>
</body></html>
"""


def landing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=LANDING, headers={"Content-Type": "text/html"})


def test_discovery_keeps_one_file_a_period(client_for):
    files = Bexley().discover(client_for(landing_handler), None, None)
    assert [f.period for f in files] == [
        "2010-11_2011-03",
        "2018-10_2018-12",
        "2024-12",
        "2025-08",
        "2025-11",
        "2026-03",
        "2026-06",
        "2026-07",
    ]
    assert all(f.format == "csv" for f in files)
    assert all(f.borough == "bexley" for f in files)


def test_the_folder_in_the_url_is_the_upload_month(client_for):
    """July 2026 sits in a 2026-08 folder and November 2025 in a 2026-01 one.

    Reading the path would date both files to the month somebody uploaded
    them, which for the oldest files is seven years out.
    """
    files = {
        f.period: f.url
        for f in Bexley().discover(client_for(landing_handler), None, None)
    }
    assert files["2026-07"].endswith("/2026-08/july-2026.csv")
    assert files["2025-11"].endswith("/2026-01/November-2025-v1.csv")


def test_the_card_sections_are_dropped_whole(client_for):
    """The card file for November 2025 is the one named like an ordinary month.

    ``november-2025.csv`` under the card heading and ``November-2025-v1.csv``
    under the year heading are the same month in two datasets, so only the
    section the link sits in can tell them apart.
    """
    files = {
        f.period: f.url
        for f in Bexley().discover(client_for(landing_handler), None, None)
    }
    assert "/2025-12/november-2025.csv" not in files["2025-11"]
    assert "2026-08" not in files  # the August 2026 card file, and no other August
    assert (
        "2025-06" not in files
    )  # publication_payments_over_June_2025.csv is a card file


def test_a_span_becomes_the_range_it_covers(client_for):
    """Eight years of half-year and whole-year files, no longer left behind.

    "October to December (CSV)" carries no year and its file name does, so the
    two together are what date it. Reading either alone would file a quarter
    of spending under December 2018.
    """
    files = {
        f.period: f.url
        for f in Bexley().discover(client_for(landing_handler), None, None)
    }
    assert files["2018-10_2018-12"].endswith("/October-December-2018.csv")
    assert files["2010-11_2011-03"].endswith(
        "/November-2010-to-March-2011-CSV-format.csv"
    )
    assert "2018-12" not in files


def test_a_label_that_contradicts_its_own_file_is_left_alone(client_for, caplog):
    """One 2017 link points at a 2018 purchase card file.

    Believing either half would put card transactions on disk under a quarter
    of 2017. The link is counted and skipped, and April to June 2017 stays
    missing, because Bexley does not currently link it anywhere.
    """
    with caplog.at_level(logging.WARNING, logger="spend_indexer.boroughs.bexley"):
        files = Bexley().discover(client_for(landing_handler), None, None)
    assert not any("April-to-December-2018" in f.url for f in files)
    assert not any(f.period.startswith("2017") for f in files)
    assert "skipped 1 link(s)" in caplog.text


def test_a_window_inside_a_span_still_finds_the_file(client_for):
    """A --since of January 2011 reaches a file that opened in November 2010."""
    files = Bexley().discover(client_for(landing_handler), "2011-01", "2011-01")
    assert [f.period for f in files] == ["2010-11_2011-03"]


def test_discover_honours_since_and_until(client_for):
    files = Bexley().discover(client_for(landing_handler), "2025-01", "2026-03")
    assert [f.period for f in files] == ["2025-08", "2025-11", "2026-03"]


def test_a_typo_in_the_label_still_leaves_a_month(client_for):
    """The December 2024 link is labelled "December 2024 (CS)V"."""
    files = Bexley().discover(client_for(landing_handler), "2024-12", "2024-12")
    assert files[0].url.endswith("/Dec_24_v3.csv")


@pytest.mark.parametrize(
    ("label", "name", "expected"),
    [
        ("April to September 2019", "x.csv", "2019-04_2019-09"),
        ("October 2014 to March 2015", "x.csv", "2014-10_2015-03"),
        ("October to December (CSV)", "October-December-2018.csv", "2018-10_2018-12"),
        ("April 2011 to March 2012", "x.csv", "2011-04_2012-03"),
        # One month stays one month, whichever of the two spells it.
        ("July 2026 (CSV)", "july-2026.csv", "2026-07"),
        ("December 2024 (CS)V", "Dec_24_v3.csv", "2024-12"),
        ("", "Aug_2025_v1.csv", "2025-08"),
        ("", "may-2026-spend-report.csv", "2026-05"),
        ("", "expenditure-records.csv", None),
    ],
)
def test_link_period_reads_a_month_or_a_span(label, name, expected):
    assert link_period(label, name) == expected


def test_an_undated_link_is_counted_not_guessed_at(client_for, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                "<h4>2026</h4><p>"
                '<a href="/sites/default/files/2026-08/july-2026.csv">July 2026</a>'
                '<a href="/sites/default/files/2026-08/expenditure.csv">Expenditure</a>'
                "</p>"
            ),
            headers={"Content-Type": "text/html"},
        )

    with caplog.at_level(logging.WARNING, logger="spend_indexer.boroughs.bexley"):
        files = Bexley().discover(client_for(handler), None, None)
    assert [f.period for f in files] == ["2026-07"]
    assert "skipped 1 link(s)" in caplog.text


def test_a_section_is_the_markup_between_two_headings():
    sections = expenditure_sections(LANDING)
    joined = "".join(sections)
    assert "November-2025-v1.csv" in joined
    assert "pcard-expenditure-august-2026.csv" not in joined
    assert "publication_payments_over_June_2025.csv" not in joined
