"""Camden: budget books on the financial strategy page, 2015/16 to 2026/27.

Camden's committee portal is behind a Cloudflare challenge, but none of that
matters here: the council's own financial strategy page carries the budget
books directly, and it answers a plain request.

Two things about the URLs. The current books are
``/documents/d/guest/<slug>`` with no extension at all and the body is PDF;
the older ones are ``/documents/20142/5611054/<name>.pdf/<uuid>``, where the
filename sits one segment from the end. ``filename_from_url`` handles both.

The page also lists medium-term financial strategy reviews, July financial
position updates and monthly outturn forecasts. Those are monitoring rather
than budget, and they are filed by report date rather than by the year they
cover, so the label filter takes the books and the code books only.
"""

from __future__ import annotations

import re

from ._budgetbook import BudgetBookSource


class CamdenBudget(BudgetBookSource):
    slug = "camden-budget"
    name = "Camden"
    landing_page = "https://www.camden.gov.uk/financial-strategy"
    link_pattern = r"camden\.gov\.uk/documents/"
    #: "Budget Book for 2026/27" and "Budget Code Book for 2016/17", which is
    #: the cost-centre key to the book beside it.
    label_pattern = re.compile(r"budget\s+(code\s+)?book", re.IGNORECASE)
