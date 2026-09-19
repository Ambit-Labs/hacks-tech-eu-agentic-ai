"""Brent: Budget and Council Tax Setting Meeting papers, 2020 to 2026.

The cleanest committee route of the four. The single "Budget and Council Tax"
agenda item carries 27 linked documents: the report, the council tax
resolution, and appendices that run from the general fund summary through the
capital programme, the HRA business plan and the treasury management strategy.

Brent's document filenames contain spaces, which the manifest replaces on the
way to disk.
"""

from __future__ import annotations

from ._moderngov import ModernGovBudgetSource


class BrentBudget(ModernGovBudgetSource):
    slug = "brent-budget"
    name = "Brent"
    host = "https://democracy.brent.gov.uk"
    landing_page = (
        "https://www.brent.gov.uk/the-council-and-democracy/budgets-and-spending"
    )
    #: Council. Brent also has a "Council Tax Setting Committee" (784), which
    #: handles the resolution rather than the budget.
    committee_id = 180
