"""Wandsworth: nineteen council budgets, 2008/09 to 2026/27, one file each.

The same CMS and the same shared finance team as Richmond, so the same shape:
one PDF per financial year at ``/media/{hash}/council_budget_{fy}.pdf``. The
2026/27 book is 258 pages and covers the general fund, subjective analysis,
budgets by committee, capital, treasury management, the Housing Revenue
Account, the dedicated schools budget, the medium-term financial strategy and
the pension fund, in that order.

Wandsworth calls it "council budget" rather than "budget book", which is why
the label filter here is looser than Richmond's.
"""

from __future__ import annotations

import re

from ._budgetbook import UmbracoBudgetBookSource


class WandsworthBudget(UmbracoBudgetBookSource):
    slug = "wandsworth-budget"
    name = "Wandsworth"
    host = "https://www.wandsworth.gov.uk"
    landing_page = (
        "https://www.wandsworth.gov.uk/the-council/how-the-council-works"
        "/council-finances/council-budget/"
    )
    link_pattern = r"/media/[^/]+/.*\.pdf$"
    label_pattern = re.compile(r"council\s+budget", re.IGNORECASE)
    stem = "council_budget"
    #: 2019/20 and earlier are ``council_budget_201920.pdf``, with no separator
    #: between the halves, so the generated pattern only claims 2020/21 on.
    pattern_from = 2020
