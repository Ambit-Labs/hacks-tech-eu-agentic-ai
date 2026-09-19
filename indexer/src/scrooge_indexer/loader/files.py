"""Which files on disk a load run is about, and what period each one covers.

The period is read from the borough's `manifest.json` where there is an entry
for the file, and from the `<period>__<name>` prefix where there is not. Both
say the same thing for everything the downloader wrote; the filename is the
fallback for a file somebody copied in by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import manifest
from ..boroughs import get_source
from ..boroughs.base import DEFAULT_QUARTERS, in_range, parse_period
from ..config import raw_dir
from .mappings import SPEND_BOROUGHS

#: What `source_files.path` holds, as the DDL comment says. Always this shape,
#: whatever `--data-dir` points at, so a load from a copy of the tree writes
#: the same key as a load from the repo.
CANONICAL_ROOT = "data/raw"


@dataclass(frozen=True)
class SpendFile:
    """One file under data/raw, with the period it covers."""

    borough: str
    path: Path
    relpath: str
    period: str

    @property
    def name(self) -> str:
        return self.path.name


def _period_of(name: str) -> str:
    """`2019-09__camden.csv` → `2019-09`. Falls back to reading the whole name."""
    prefix = name.split("__", 1)[0] if "__" in name else ""
    if prefix and (
        prefix[:4].isdigit() and (len(prefix) == 7 or "_" in prefix or "-Q" in prefix)
    ):
        return prefix
    return parse_period(name) or "unknown"


def borough_files(data_dir: Path, slug: str) -> list[SpendFile]:
    """Every spend file on disk for one borough, sorted by period then name."""
    directory = raw_dir(data_dir, slug, "spend")
    if not directory.is_dir():
        return []
    periods = {
        Path(entry.path).name: entry.period
        for entry in manifest.load(data_dir, slug, "spend").entries.values()
    }
    files = [
        SpendFile(
            borough=slug,
            path=path,
            relpath=f"{CANONICAL_ROOT}/{slug}/{path.name}",
            period=periods.get(path.name) or _period_of(path.name),
        )
        for path in sorted(directory.iterdir())
        if path.is_file() and path.name != manifest.MANIFEST_NAME
    ]
    files.sort(key=lambda f: (f.period, f.name))
    return files


def select(
    data_dir: Path,
    slugs: list[str],
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
) -> list[SpendFile]:
    """The files a load run will walk, in the order it will walk them."""
    chosen: list[SpendFile] = []
    for slug in slugs:
        source = get_source(slug)
        quarters = source.quarters if source is not None else DEFAULT_QUARTERS
        found = [
            spend_file
            for spend_file in borough_files(data_dir, slug)
            if spend_file.period == "unknown"
            or in_range(spend_file.period, since, until, quarters=quarters)
        ]
        if limit:
            # The most recent N, the same rule `scrooge download --limit` uses,
            # because a capped run is nearly always a smoke test.
            found = found[-limit:]
        chosen.extend(found)
    return chosen


def known_boroughs(data_dir: Path) -> list[str]:
    """Boroughs with both a mapping here and files on disk."""
    return [
        slug for slug in SPEND_BOROUGHS if raw_dir(data_dir, slug, "spend").is_dir()
    ]
