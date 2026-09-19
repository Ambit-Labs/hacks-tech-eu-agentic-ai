"""Hounslow: Budget Setting Meeting papers from the self-hosted Modern.Gov.

Hounslow's budget page links the statement of accounts and the open data
portal, but not the budget itself: that lives on the committee system. The
Borough Council budget meeting carries the reference report from Cabinet plus
appendices A to I as separate PDFs, which is where the service-level numbers
are (Appendix B is the general fund budget summary, E the capital programme).

Ten budget meetings are labelled as such, 2013 to 2026.
"""

from __future__ import annotations

from ._moderngov import ModernGovBudgetSource


class HounslowBudget(ModernGovBudgetSource):
    slug = "hounslow-budget"
    name = "Hounslow"
    host = "https://democraticservices.hounslow.gov.uk"
    landing_page = (
        "https://www.hounslow.gov.uk/find-data-information/council-budgets-spending"
    )
    #: Borough Council, the meeting that sets the budget. Cabinet (571)
    #: recommends it three weeks earlier with the same appendices attached.
    committee_id = 254
