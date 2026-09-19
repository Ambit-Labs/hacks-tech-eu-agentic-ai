"""Lambeth: Budget Council papers, including the MTFS that exists nowhere else.

Lambeth's Budget Council agenda carries the budget report, its addendum, the
gross and net budgets by directorate, the capital investment programme, and
"Appendix 01 - MTFS 2026-30". That last one matters: MHCLG collects one budget
year at a time, so a borough's medium-term financial strategy is only ever in
its own committee papers.

The agenda also holds the opposition groups' alternative budgets, each with the
section 151 officer's statement on it. Those are budget documents too and they
are kept.

Eight meetings are labelled "Budget Council": 2011, then 2019 to 2026 except
2022. The years in between were held under the plain "Confirmed" status and are
not reachable by label.
"""

from __future__ import annotations

from ._moderngov import ModernGovBudgetSource


class LambethBudget(ModernGovBudgetSource):
    slug = "lambeth-budget"
    name = "Lambeth"
    host = "https://moderngov.lambeth.gov.uk"
    landing_page = (
        "https://www.lambeth.gov.uk/about-council/transparency-open-data"
        "/financial-information"
    )
    #: Council. Cabinet is 225 and recommends the same pack a week earlier.
    committee_id = 142
