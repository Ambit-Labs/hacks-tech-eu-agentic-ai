"""Richmond upon Thames: monthly CSVs on the shared Richmond/Wandsworth CMS.

Richmond also publishes quarterly procurement card spend
(``procurement_card_spend_2026_27_q1.csv``) on the same page. Left out for now:
it is a different dataset with different columns, and mixing it into the
monthly series would make the period axis lie.
"""

from __future__ import annotations

from ._umbraco import UmbracoExpenditureSource


class Richmond(UmbracoExpenditureSource):
    slug = "richmond"
    name = "Richmond upon Thames"
    host = "https://www.richmond.gov.uk"
    landing_page = "https://www.richmond.gov.uk/council_payments_to_suppliers"
