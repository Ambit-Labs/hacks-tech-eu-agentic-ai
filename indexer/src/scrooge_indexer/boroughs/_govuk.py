"""Resolving GOV.UK statistics files through the content API.

Every file MHCLG publishes lives at
``assets.publishing.service.gov.uk/media/{hash}/{name}``, and the hash is
regenerated on every release. Hard-coding one is a link that breaks the next
time a table is corrected. The content API is the way out: ``/api/content`` +
the page path returns the same page as JSON, and ``details.attachments[].url``
is the current location of each file. No key, no quota, and the answer is the
publisher's own, not a guess.

Two shapes matter. A *collection* page carries ``links.documents``, which is
how a new year appears without code changes: the collection lists the release
and the release lists its files. A *release* page carries
``details.attachments``.

Underscore-prefixed so the registry skips it: shared machinery, not a source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import httpx

from ..http import request_with_retries

CONTENT_API = "https://www.gov.uk/api/content"

#: Where the files themselves live. An attachment pointing anywhere else is an
#: HTML page (guidance, technical notes) rendered as an attachment, and those
#: come back as site-relative paths with no host at all.
ASSET_HOST = "https://assets.publishing.service.gov.uk/"


@dataclass(frozen=True)
class Attachment:
    """One downloadable file on a GOV.UK release page."""

    title: str
    url: str

    @property
    def filename(self) -> str:
        return unquote(urlsplit(self.url).path.rsplit("/", 1)[-1])


@dataclass(frozen=True)
class Release:
    """One publication or statistics release, as the content API returns it."""

    path: str
    title: str
    attachments: tuple[Attachment, ...]

    def matching(self, pattern: re.Pattern[str]) -> list[Attachment]:
        """Attachments whose filename or title matches, filename tried first.

        Both are needed. From 2016 onwards MHCLG names the files themselves
        (``RA_2023-24_data_Part_1.ods``), but the 2010-11 release calls its
        files ``1934015.xls`` and only the attachment title says which return
        it is.
        """
        return [
            a
            for a in self.attachments
            if pattern.search(a.filename) or pattern.search(a.title)
        ]


def fetch(client: httpx.Client, path: str) -> dict:
    """The content API item for a GOV.UK page path."""
    response = request_with_retries(client, "GET", f"{CONTENT_API}{path}")
    return response.json()


def release(client: httpx.Client, path: str) -> Release:
    """Fetch one release and keep only the attachments that are really files."""
    item = fetch(client, path)
    details = item.get("details") or {}
    attachments = tuple(
        Attachment(title=raw.get("title") or "", url=url)
        for raw in details.get("attachments") or []
        if (url := (raw.get("url") or "")).startswith(ASSET_HOST)
    )
    return Release(path=path, title=item.get("title") or path, attachments=attachments)


def collection_documents(client: httpx.Client, path: str) -> list[tuple[str, str]]:
    """``[(page path, title)]`` for every release a collection lists.

    This is the half that makes a new year free: MHCLG adds the 2027-28 budget
    release to the collection when it publishes it, and a source that reads the
    collection finds it without anybody editing a list of paths.
    """
    item = fetch(client, path)
    return [
        (doc["base_path"], doc.get("title") or "")
        for doc in (item.get("links") or {}).get("documents") or []
        if doc.get("base_path")
    ]


#: ``...-england-2026-to-2027-budget-individual-local-authority-data``, and the
#: ``--6`` GOV.UK appends when a path collided with an older one.
_PATH_YEARS = re.compile(r"-(\d{4})-to-(\d{4})(?:-|$)")


def path_years(path: str) -> tuple[int, int] | None:
    """The financial year a release path names, as ``(start, end)``.

    The path is the reliable place to read it. Release titles drift ("revised",
    "third release") and attachment filenames went numeric before 2016, but the
    slug has spelled the year the same way since 2010.
    """
    match = _PATH_YEARS.search(path)
    if not match:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    return (start, end) if end == start + 1 else None
