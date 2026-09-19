"""Merton: rolling four-year budget books, and the business plans before them.

Merton publishes one book covering four financial years at a time, so the
2026-30 edition is ``2026-04_2030-03`` rather than a single year, and a query
for any year inside that span reaches it. Four editions exist in that format
(2023-27 to 2026-30); before them the same job was done by a Business Plan,
back to 2013-17, so both labels are taken.

Merton's Modern.Gov instance refuses every automated request, which costs the
council tax resolution and the in-year monitoring reports. The budget book
itself is on the council's own CMS and answers a plain request; it carries the
medium-term financial strategy, the capital strategy and programme, the
treasury management strategy and the revenue estimates in one 327-page file.
"""

from __future__ import annotations

import re

from ._budgetbook import BudgetBookSource


class MertonBudget(BudgetBookSource):
    slug = "merton-budget"
    name = "Merton"
    landing_page = (
        "https://www.merton.gov.uk/council-and-local-democracy/finance/budgets"
    )
    link_pattern = r"merton\.gov\.uk/.*\.pdf$"
    label_pattern = re.compile(r"budget\s+book|business\s+plan", re.IGNORECASE)
