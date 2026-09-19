"""Richmond upon Thames: twenty budget books, 2007/08 to 2026/27.

The best-organised budget page in this corpus. One Umbraco page lists every
year as a direct PDF, and each book is the whole thing in one file: the revenue
budget strategy and council tax report, detailed tables per committee and
service area, the capital programme, and the medium-term financial strategy.

The landing page also links treasury management reports on the Modern.Gov host
and a stale duplicate of the capital programme report under an older document
id. Neither is a budget book, and the label filter keeps both out.
"""

from __future__ import annotations

import re

from ._budgetbook import UmbracoBudgetBookSource


class RichmondBudget(UmbracoBudgetBookSource):
    slug = "richmond-budget"
    name = "Richmond upon Thames"
    host = "https://www.richmond.gov.uk"
    landing_page = "https://www.richmond.gov.uk/budgets_and_spending"
    link_pattern = r"/media/[^/]+/.*\.pdf$"
    label_pattern = re.compile(r"budget\s+book", re.IGNORECASE)
    stem = "budget_book"
    pattern_from = 2016
