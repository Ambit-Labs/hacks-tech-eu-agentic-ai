"""Wandsworth: monthly CSVs on the shared Richmond/Wandsworth CMS.

Same class as Richmond, different host and landing page. Wandsworth publishes
no procurement card file; its grants go through committee papers and are not
structured data.
"""

from __future__ import annotations

from ._umbraco import UmbracoExpenditureSource


class Wandsworth(UmbracoExpenditureSource):
    slug = "wandsworth"
    name = "Wandsworth"
    host = "https://www.wandsworth.gov.uk"
    landing_page = (
        "https://www.wandsworth.gov.uk/the-council/how-the-council-works/"
        "council-finances/council-expenditure/"
    )
