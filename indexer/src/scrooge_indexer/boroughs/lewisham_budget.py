"""Lewisham: corporate budget books, 2012-13 to 2026-27.

Fourteen years of directorate-by-service tables (employees, premises,
transport, supplies, third party, income, in £000) plus a four-year capital
programme and an HRA section, one PDF per year on the council's own CMS.

The path prefix has changed at least three times across those years
(``/-/media/mayor-and-council/...``, ``/-/media/archive/``,
``/-/media/archive/files/imported/``), which is why the page is scraped and no
URL is ever guessed. Some labels use an en dash ("2019–20"), which the
financial-year parser reads the same as a hyphen.

Both Modern.Gov mirrors refuse automated requests, so the formal budget report
to Council and its appendices are out of reach. The corporate budget book is
the service-level source and it is open.
"""

from __future__ import annotations

import re

from ._budgetbook import BudgetBookSource


class LewishamBudget(BudgetBookSource):
    slug = "lewisham-budget"
    name = "Lewisham"
    landing_page = (
        "https://lewisham.gov.uk/mayorandcouncil/aboutthecouncil/finances/budgets"
    )
    link_pattern = r"lewisham\.gov\.uk/.*\.pdf(\?|$)"
    label_pattern = re.compile(r"budget\s+book", re.IGNORECASE)
