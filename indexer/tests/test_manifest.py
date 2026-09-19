"""Filenames, resume semantics, and the mutable-file contract."""

from __future__ import annotations

import pytest

from scrooge_indexer import manifest
from scrooge_indexer.models import RemoteFile


@pytest.mark.parametrize(
    ("raw", "fmt", "expected"),
    [
        (
            "council_expenditure_july_2026.csv",
            "csv",
            "council_expenditure_july_2026.csv",
        ),
        ("Expenditure Report July 2026.csv", "csv", "Expenditure-Report-July-2026.csv"),
        ("../../etc/passwd", "csv", "passwd.csv"),
        ("a/b/c/report.CSV", "csv", "report.csv"),
        # Westminster: the URL ends in a document id with no extension at all.
        (
            "q1-2026-27-expenditure-over-£500",
            "csv",
            "q1-2026-27-expenditure-over-500.csv",
        ),
        (
            "July 2026 Transparency (CSV) Copy.xlsx.csv",
            "csv",
            "July-2026-Transparency-CSV-Copy.xlsx.csv",
        ),
        ("", "csv", "file.csv"),
    ],
)
def test_safe_filename(raw, fmt, expected):
    assert manifest.safe_filename(raw, fmt) == expected


def test_safe_filename_never_escapes_the_borough_directory():
    assert "/" not in manifest.safe_filename("../../../root/.ssh/id_rsa", "csv")


def _remote(period="2026-07", url="https://example.invalid/a.csv", mutable=False):
    return RemoteFile(
        borough="testborough",
        period=period,
        url=url,
        filename="council_expenditure_july_2026.csv",
        format="csv",
        mutable=mutable,
    )


def test_relative_path_is_period_then_safe_name():
    assert manifest.relative_path(_remote()) == (
        "raw/testborough/2026-07__council_expenditure_july_2026.csv"
    )


def test_save_and_load_round_trip(tmp_path):
    book = manifest.load(tmp_path, "testborough")
    remote = _remote()
    manifest.record(book, remote, status="ok", bytes_=12, sha256="abc")
    manifest.save(tmp_path, book)
    again = manifest.load(tmp_path, "testborough")
    assert again.entries[remote.key].bytes == 12
    assert again.entries[remote.key].sha256 == "abc"
    # No temp file survives a completed write.
    assert not (tmp_path / "raw/testborough/manifest.json.tmp").exists()


def test_corrupt_manifest_reads_as_empty_rather_than_crashing(tmp_path):
    path = manifest.manifest_path(tmp_path, "testborough")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert manifest.load(tmp_path, "testborough").entries == {}


def test_resume_skips_only_a_recorded_file_that_is_still_on_disk(tmp_path):
    book = manifest.load(tmp_path, "testborough")
    remote = _remote()
    manifest.record(book, remote, status="ok", bytes_=12)
    assert manifest.should_skip(book, remote, tmp_path) is False  # no file yet

    dest = manifest.dest_path(tmp_path, remote)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("payload", encoding="utf-8")
    assert manifest.should_skip(book, remote, tmp_path) is True

    dest.unlink()
    assert manifest.should_skip(book, remote, tmp_path) is False


def test_force_never_skips(tmp_path):
    book = manifest.load(tmp_path, "testborough")
    remote = _remote()
    manifest.record(book, remote, status="ok")
    manifest.dest_path(tmp_path, remote).parent.mkdir(parents=True, exist_ok=True)
    manifest.dest_path(tmp_path, remote).write_text("x", encoding="utf-8")
    assert manifest.should_skip(book, remote, tmp_path, force=True) is False


def test_a_failed_entry_is_retried(tmp_path):
    book = manifest.load(tmp_path, "testborough")
    remote = _remote()
    manifest.record(book, remote, status="failed", error="HTTP 500")
    assert manifest.should_skip(book, remote, tmp_path) is False


def test_mutable_files_are_never_skipped_but_carry_validators(tmp_path):
    book = manifest.load(tmp_path, "testborough")
    remote = _remote(mutable=True)
    manifest.record(
        book,
        remote,
        status="ok",
        etag='W/"abc"',
        last_modified="Wed, 02 Sep 2026 00:00:00 GMT",
    )
    dest = manifest.dest_path(tmp_path, remote)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("x", encoding="utf-8")

    assert manifest.should_skip(book, remote, tmp_path) is False
    assert manifest.conditional_headers(book, remote, tmp_path) == {
        "If-None-Match": 'W/"abc"',
        "If-Modified-Since": "Wed, 02 Sep 2026 00:00:00 GMT",
    }


def test_conditional_headers_are_empty_when_the_file_is_gone(tmp_path):
    book = manifest.load(tmp_path, "testborough")
    remote = _remote(mutable=True)
    manifest.record(book, remote, status="ok", etag='W/"abc"')
    assert manifest.conditional_headers(book, remote, tmp_path) == {}


def test_a_new_url_for_the_same_period_is_a_new_entry(tmp_path):
    """A council reuploads a month under a new media hash. Both are recorded,
    and the new one is fetched rather than skipped as already done."""
    book = manifest.load(tmp_path, "testborough")
    old = _remote(url="https://example.invalid/media/aaaa/july.csv")
    new = _remote(url="https://example.invalid/media/bbbb/july.csv")
    manifest.record(book, old, status="ok")
    manifest.dest_path(tmp_path, old).parent.mkdir(parents=True, exist_ok=True)
    manifest.dest_path(tmp_path, old).write_text("x", encoding="utf-8")
    assert manifest.should_skip(book, new, tmp_path) is False


def test_relative_path_keeps_a_range_readable(tmp_path):
    """One underscore inside the period, two before the publisher's name."""
    assert manifest.relative_path(_remote(period="2010-09_2011-03")) == (
        "raw/testborough/2010-09_2011-03__council_expenditure_july_2026.csv"
    )


def test_summarise_dates_a_range_and_a_quarter_by_the_months_they_cover(tmp_path):
    """The strings do not sort chronologically; the months they cover do.

    ``2010-09_2011-03`` closes after ``2010-12``, and ``2025-Q4`` closes in
    March 2026, neither of which a plain string comparison would say.
    """
    book = manifest.load(tmp_path, "testborough")
    for period in ("2010-09_2011-03", "2010-12", "2025-Q4"):
        remote = _remote(period=period, url=f"https://example.invalid/{period}.csv")
        manifest.record(book, remote, status="ok", bytes_=1)
        dest = manifest.dest_path(tmp_path, remote)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x", encoding="utf-8")
    manifest.save(tmp_path, book)

    summary = manifest.summarise(tmp_path, "testborough")
    assert summary["earliest"] == "2010-09_2011-03"
    assert summary["latest"] == "2025-Q4"


def test_summarise(tmp_path):
    book = manifest.load(tmp_path, "testborough")
    for period in ("2026-05", "2026-06", "2026-07"):
        remote = _remote(period=period, url=f"https://example.invalid/{period}.csv")
        manifest.record(book, remote, status="ok", bytes_=100)
        dest = manifest.dest_path(tmp_path, remote)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x", encoding="utf-8")
    manifest.record(
        book,
        _remote(period="2026-08", url="https://example.invalid/8.csv"),
        status="failed",
    )
    manifest.save(tmp_path, book)

    summary = manifest.summarise(tmp_path, "testborough")
    assert summary["files"] == 3
    assert summary["bytes"] == 300
    assert summary["earliest"] == "2026-05"
    assert summary["latest"] == "2026-07"
    assert summary["failures"] == 1
    assert manifest.files_on_disk(tmp_path, "testborough") == 3
