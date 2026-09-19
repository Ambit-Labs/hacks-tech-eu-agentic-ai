"""Haringey: Full Council budget papers, with per-directorate appendices.

The budget item on Haringey's Full Council agenda carries 26 documents, the
report plus appendices broken out by directorate. Haringey's own budget page
holds only the current year, so the committee archive is the history.

Five meetings are labelled "Budget": 2020, 2022, 2023, 2025 and 2026. The
others were not labelled, so they are not reachable by label; see
``_moderngov`` for why that is preferred to guessing.

Document filenames on this host are messy, including things like
``...ver1.0 003.docx_updated 7.30.pdf``. The title is what names the file here,
not the URL, so that does not reach disk.
"""

from __future__ import annotations

from ._moderngov import ModernGovBudgetSource


class HaringeyBudget(ModernGovBudgetSource):
    slug = "haringey-budget"
    name = "Haringey"
    host = "https://www.minutes.haringey.gov.uk"
    landing_page = (
        "https://haringey.gov.uk/council-elections/data-finance/council-budget"
    )
    #: Full Council. Cabinet is 118 and recommends the budget in February.
    committee_id = 143
