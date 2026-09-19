"""London Datastore: council tax by band and borough, 1999-00 to date.

The only place all eight bands are published per borough in one download.
MHCLG's Table 10 gives the council tax requirement and the band D figure;
this gives what a household in each band actually pays, and it goes back to
1999-00, which is twenty-seven years further than anything else here.

One DataPress dataset (``expnl``) with one resource: an XLSX with a sheet per
financial year plus a metadata sheet, ``Code`` (ONS ``E09``), ``Local
authority``, ``Band A`` to ``Band H``. The GLA publishes it as a whole, so the
period is the whole span and the file is mutable: each April a sheet is added
and the same resource URL is overwritten.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import httpx

from ..models import RemoteFile, format_from_name
from .base import Source, datapress_resources, fy_period

PORTAL = "https://data.london.gov.uk"
PACKAGE = "expnl"

#: Financial years in the workbook, verified 2026-09-19: sheets ``1999-00``
#: through ``2026-27``. Read from the sheet names, which this tool does not
#: open, so it is declared. The file is mutable, so a new sheet arrives on its
#: own; bump the end year when it does and the period stops understating it.
SPAN = (1999, 2027)


class LondonDatastoreCouncilTax(Source):
    slug = "london-datastore-counciltax"
    name = "London Datastore council tax by band"
    kind = "budget"
    threshold = "n/a"
    access = "datapress-api"
    landing_page = (
        "https://data.london.gov.uk/dataset/council-tax-charges-bands-borough"
    )

    def discover(
        self, client: httpx.Client, since: str | None, until: str | None
    ) -> list[RemoteFile]:
        """One ``package_show``. The dataset has held one resource since 2013.

        The resource is named ``.xls`` and served as ``.xlsx``; the URL is what
        decides, because that is what lands on disk.
        """
        return [
            RemoteFile(
                borough=self.slug,
                period=fy_period(*SPAN),
                url=resource.url,
                filename=unquote(urlsplit(resource.url).path.rsplit("/", 1)[-1]),
                format=format_from_name(resource.url, "xlsx"),
                title=resource.name or "Council tax charges by band, borough",
                mutable=True,
            )
            for resource in datapress_resources(client, PORTAL, PACKAGE)
            if resource.url
        ]
