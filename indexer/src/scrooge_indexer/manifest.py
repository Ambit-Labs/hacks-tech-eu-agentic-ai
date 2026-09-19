"""One ``manifest.json`` per borough: what is on disk, and what to skip.

Written atomically after every single file rather than once at the end. A
backfill is ninety-odd requests over half an hour and it will be interrupted,
so the invariant is that the manifest on disk always describes the files on
disk. A torn manifest would be worse than no manifest: resume would skip a
file that was never written.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from .boroughs.base import period_bounds
from .config import raw_dir
from .models import BoroughManifest, ManifestEntry, RemoteFile

MANIFEST_NAME = "manifest.json"

#: Everything outside this set is replaced with a hyphen in a saved filename.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_DASHES = re.compile(r"-{2,}")


def utc_now() -> str:
    """UTC, ISO 8601, second precision. Manifest timestamps sort as strings."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def safe_filename(name: str, fmt: str | None = None) -> str:
    """A publisher's filename reduced to something safe to write and to read.

    Path separators go first (a council filename with a slash in it would
    otherwise escape the borough directory), then spaces, brackets, pound
    signs and percent-escapes collapse to hyphens. The extension is kept when
    there is one and appended from ``fmt`` when there is not, which is what
    Westminster needs: its URLs end in a document id with no extension at all
    and the body is CSV.
    """
    base = Path(name.replace("\\", "/")).name or "file"
    stem, dot, suffix = base.rpartition(".")
    if not dot or len(suffix) > 5 or not suffix.isalnum():
        stem, suffix = base, ""
    cleaned = _DASHES.sub("-", _UNSAFE.sub("-", stem)).strip("-._") or "file"
    suffix = _UNSAFE.sub("", suffix).lower()
    if not suffix and fmt:
        suffix = fmt
    return f"{cleaned}.{suffix}" if suffix else cleaned


def relative_path(remote: RemoteFile) -> str:
    """``raw/<slug>/<period>__<safe-name>``, relative to the data directory."""
    return f"raw/{remote.borough}/{remote.period}__{safe_filename(remote.filename, remote.format)}"


def dest_path(data_dir: Path, remote: RemoteFile) -> Path:
    return Path(data_dir) / relative_path(remote)


def manifest_path(data_dir: Path, slug: str) -> Path:
    return raw_dir(data_dir, slug) / MANIFEST_NAME


def load(data_dir: Path, slug: str) -> BoroughManifest:
    """Read a borough's manifest, or an empty one when there is nothing yet.

    A manifest that fails to parse is treated as absent rather than fatal: the
    files are still on disk, and a re-download that rebuilds the record is a
    better outcome than a CLI that refuses to run.
    """
    path = manifest_path(data_dir, slug)
    if not path.is_file():
        return BoroughManifest(borough=slug)
    try:
        return BoroughManifest.model_validate_json(path.read_text("utf-8"))
    except (ValueError, OSError):
        return BoroughManifest(borough=slug)


def save(data_dir: Path, manifest: BoroughManifest) -> None:
    """Write the manifest through a temp file and an atomic rename."""
    path = manifest_path(data_dir, manifest.borough)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def record(
    manifest: BoroughManifest,
    remote: RemoteFile,
    *,
    status: str,
    bytes_: int = 0,
    sha256: str | None = None,
    content_type: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    error: str | None = None,
) -> ManifestEntry:
    """Put one outcome into the manifest in memory. The caller saves."""
    entry = ManifestEntry(
        url=remote.url,
        period=remote.period,
        path=relative_path(remote),
        bytes=bytes_,
        sha256=sha256,
        content_type=content_type,
        etag=etag,
        last_modified=last_modified,
        fetched_at=utc_now(),
        status=status,  # type: ignore[arg-type]
        error=error,
        title=remote.title,
        mutable=remote.mutable,
    )
    manifest.entries[remote.key] = entry
    return entry


def should_skip(
    manifest: BoroughManifest,
    remote: RemoteFile,
    data_dir: Path,
    *,
    force: bool = False,
) -> bool:
    """Is this file already done?

    True only when the manifest says ``ok`` for this exact period and URL *and*
    the file is still on disk, so deleting a file is enough to make the next
    run fetch it again. ``--force`` and ``mutable`` both answer False: a
    cumulative file is re-checked every run (conditionally, see
    :func:`conditional_headers`) because the publisher rewrites it in place.
    """
    if force or remote.mutable:
        return False
    entry = manifest.entries.get(remote.key)
    if entry is None or entry.status != "ok":
        return False
    return (Path(data_dir) / entry.path).is_file()


def conditional_headers(
    manifest: BoroughManifest, remote: RemoteFile, data_dir: Path
) -> dict[str, str]:
    """``If-None-Match`` / ``If-Modified-Since`` for a mutable file we already hold.

    The cheap half of the mutable contract: when the source honours the
    validators we get a 304 and no bytes move. When it does not (Socrata does
    not), the file is re-fetched and its sha256 decides whether anything
    actually changed, so the answer is right either way, just more expensive.
    """
    entry = manifest.entries.get(remote.key)
    if entry is None or entry.status != "ok":
        return {}
    if not (Path(data_dir) / entry.path).is_file():
        return {}
    headers: dict[str, str] = {}
    if entry.etag:
        headers["If-None-Match"] = entry.etag
    if entry.last_modified:
        headers["If-Modified-Since"] = entry.last_modified
    return headers


def files_on_disk(data_dir: Path, slug: str) -> int:
    """Count of completed files, from the manifest rather than a directory scan."""
    manifest = load(data_dir, slug)
    return sum(
        1
        for entry in manifest.entries.values()
        if entry.status == "ok" and (Path(data_dir) / entry.path).is_file()
    )


def _first_month(period: str) -> tuple[str, str]:
    """Sort key for "earliest period held": the month the period opens in."""
    return period_bounds(period)[0], period


def _last_month(period: str) -> tuple[str, str]:
    """Sort key for "latest period held": the month the period closes in.

    ``2010-09_2011-03`` is later than ``2010-12`` and ``2025-Q4`` is later than
    ``2026-01``, neither of which the strings say on their own. The financial
    convention is assumed because a manifest records periods, not the borough
    that chose the convention, and every registered borough uses it.
    """
    return period_bounds(period)[1], period


def summarise(data_dir: Path, slug: str) -> dict:
    """Per-borough numbers for ``scrooge status`` and ``scrooge list``."""
    manifest = load(data_dir, slug)
    ok = [e for e in manifest.entries.values() if e.status == "ok"]
    periods = sorted(e.period for e in ok)
    failures = [
        e for e in manifest.entries.values() if e.status in ("failed", "blocked")
    ]
    return {
        "files": len(ok),
        "bytes": sum(e.bytes for e in ok),
        "earliest": min(periods, key=_first_month) if periods else None,
        "latest": max(periods, key=_last_month) if periods else None,
        "last_run": manifest.last_run,
        "failures": len(failures),
        "missing": sum(1 for e in manifest.entries.values() if e.status == "missing"),
    }
