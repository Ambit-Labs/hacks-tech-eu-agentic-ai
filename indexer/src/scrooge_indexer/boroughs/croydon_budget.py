"""Croydon: eighteen budget books, 2009-10 to 2026-27, on one page.

The deepest service-level detail of the borough budget books: the 2026/27 book
is 246 pages and goes down to cost-centre ranges, which is a consequence of
Croydon having been under government support since its section 114 notice.

Filenames drift every year and have been through at least five conventions
(``Consolidated-Budget-Books-2026-27.pdf``, ``budget-book-2025-2026.pdf``,
``bb1112.pdf``, ``bbook1011.pdf``, ``draft-rev-budget-capital-14-15.pdf``), so
the year comes from the label and the URL is never constructed. Croydon's
committee hosts are Cloudflare-blocked, and the book on the main site is the
better source anyway.
"""

from __future__ import annotations

import re

from ._budgetbook import BudgetBookSource


class CroydonBudget(BudgetBookSource):
    slug = "croydon-budget"
    name = "Croydon"
    landing_page = "https://www.croydon.gov.uk/council-and-elections/budgets-and-spending/budget-book"
    link_pattern = r"croydon\.gov\.uk/sites/default/files/.*\.pdf$"
    label_pattern = re.compile(r"budget\s+book", re.IGNORECASE)
