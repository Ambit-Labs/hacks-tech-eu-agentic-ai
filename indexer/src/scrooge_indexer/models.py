"""The two records the whole CLI passes around: a file to fetch, a file fetched.

Pydantic rather than dataclasses because both shapes cross a serialisation
boundary (the manifest is JSON on disk and a borough module is written by
someone who is not here to be asked what a field means), so validation at the
edge is worth the dependency.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

FileFormat = Literal["csv", "xlsx", "xml", "json", "ods", "pdf"]

#: What a source publishes. ``spend`` is the transaction-level file a council
#: puts out under the transparency code; ``budget`` is planned spend, which
#: arrives as a council's budget book or as an MHCLG statistical return. The two
#: never mix on disk, so a budget book cannot be mistaken for a payment list.
SourceKind = Literal["spend", "budget"]

#: Status of one manifest entry.
#:
#: ``ok``            the file is on disk and complete.
#: ``missing``       the publisher does not have this period (an honest 404).
#: ``blocked``       403 or a bot challenge. Recorded, never worked around.
#: ``failed``        anything else: timeout, 5xx after retries, short read.
EntryStatus = Literal["ok", "missing", "blocked", "failed"]

_MONTH = r"\d{4}-(?:0[1-9]|1[0-2])"

#: ``2026-08`` monthly, ``2026-08_2026-11`` a span of months, ``2026-Q1``
#: quarterly. The separator between a period and the publisher's filename on
#: disk is two underscores, so the single one inside a range is unambiguous.
PERIOD_RE = re.compile(rf"^(?:{_MONTH}(?:_{_MONTH})?|\d{{4}}-Q[1-4])$")

EXTENSIONS: dict[str, FileFormat] = {
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".xml": "xml",
    ".json": "json",
    ".ods": "ods",
    ".pdf": "pdf",
}


class RemoteFile(BaseModel):
    """One published file, as a borough's ``discover()`` describes it.

    ``period`` is normalised across boroughs so that files from different
    councils sort and filter together:

    * ``YYYY-MM`` for a monthly file, calendar month.
    * ``YYYY-MM_YYYY-MM`` for a file covering several months: the first month,
      an underscore, the last month, both inclusive. Councils publish half
      years, whole financial years and off-cycle quarters, and a file covering
      September 2010 to March 2011 is ``2010-09_2011-03`` rather than a month
      that understates it. Build one with
      :func:`~scrooge_indexer.boroughs.base.range_period`, which collapses a
      one-month span back to a month.
    * ``YYYY-Qn`` for a quarterly file, where ``n`` is the quarter number the
      borough itself prints on the file and ``YYYY`` is the year it labels that
      quarter with. Westminster's "Q1 2026-27" is therefore ``2026-Q1`` and
      covers April to June 2026, and its "Q4 2026-27" is ``2026-Q4`` covering
      January to March 2027. A council that numbers its quarters by the
      calendar year gets calendar quarters under the same spelling. Each
      council is internally consistent, so ``2026-Q1 < 2026-Q4`` is always
      chronological within one borough. Use
      :func:`~scrooge_indexer.boroughs.base.fy_quarter_period` or
      :func:`~scrooge_indexer.boroughs.base.calendar_quarter_period` so the
      choice is explicit at the call site.

    There is no bare ``YYYY``. An annual file is a range and says which twelve
    months it holds, which for a financial year (``2013-04_2014-03``) a
    calendar year could not. A cumulative year-to-date export is the range it
    has reached, with ``mutable=True`` so it is re-checked every run.

    Budget files use the same grammar and nothing new: a budget for 2026-27 is
    ``2026-04_2027-03``, a budget book covering four years at once is
    ``2026-04_2030-03``, and a multi-year statistical time series is the range
    of its span with ``mutable=True``, because the publisher extends it in
    place when a year closes.
    """

    borough: str
    period: str
    url: str
    filename: str
    format: FileFormat
    title: str | None = None
    method: Literal["GET"] = "GET"
    params: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    mutable: bool = False
    """The publisher overwrites this file in place (a cumulative year-to-date
    export, or the current month while it is still being added to). Mutable
    files are re-checked on every run and replaced when the source changed,
    never appended to."""

    @field_validator("period")
    @classmethod
    def _check_period(cls, value: str) -> str:
        if not PERIOD_RE.match(value):
            raise ValueError(
                f"period {value!r} is not YYYY-MM, YYYY-MM_YYYY-MM or YYYY-Qn"
            )
        if "_" in value:
            first, last = value.split("_")
            # A backwards range would filter as an empty window and sort as a
            # month it does not contain; an equal one is a month written long.
            if first >= last:
                raise ValueError(f"period {value!r} does not run forwards")
        return value

    @property
    def key(self) -> str:
        """Manifest key: period plus URL.

        Two things can change independently. A borough republishes the same
        period at a new URL (a new media hash), and the same URL can carry a
        different period once a publisher renumbers. Keying on the pair means
        neither case silently reuses the other's record.
        """
        return f"{self.period}|{self.url}"


class ManifestEntry(BaseModel):
    """What one fetch left behind, as written to ``manifest.json``."""

    url: str
    period: str
    path: str
    """Relative to the data directory, so the manifest survives a moved tree."""
    bytes: int = 0
    sha256: str | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    fetched_at: str
    """UTC ISO 8601, second precision."""
    status: EntryStatus = "ok"
    error: str | None = None
    title: str | None = None
    mutable: bool = False


class BoroughManifest(BaseModel):
    """Every entry for one source, plus when that source was last swept."""

    borough: str
    kind: SourceKind = "spend"
    """Which tree the entries live under, so :func:`~scrooge_indexer.manifest.save`
    and :func:`~scrooge_indexer.manifest.record` can find their own directory
    without the caller repeating it. Defaults to ``spend``, which is what every
    manifest written before budgets existed holds."""
    last_run: str | None = None
    entries: dict[str, ManifestEntry] = Field(default_factory=dict)


def format_from_name(name: str, default: FileFormat = "csv") -> FileFormat:
    """Guess a file format from a filename or URL path.

    ``default`` is what Westminster needs: its URLs carry no extension at all
    and the body is CSV, so the caller states the format it knows rather than
    letting a guess decide.
    """
    lowered = name.lower().split("?", 1)[0]
    for suffix, fmt in EXTENSIONS.items():
        if lowered.endswith(suffix):
            return fmt
    return default
