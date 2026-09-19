"""``--kind``: which sources a verb acts on, and which tree they write to."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer import cli, manifest
from scrooge_indexer.boroughs.base import Source
from scrooge_indexer.models import RemoteFile

BUDGET_BYTES = "%PDF-1.4 a budget book\n"


class FakeBudget(Source):
    """A budget source with one file, so the tree and the flags can be tested."""

    slug = "testville-budget"
    name = "Testville"
    kind = "budget"
    threshold = "n/a"
    access = "scrape"
    landing_page = "https://example.invalid/budget"

    def discover(self, client, since, until):
        return [
            RemoteFile(
                borough=self.slug,
                period="2026-04_2027-03",
                url="https://example.invalid/budget_book_2026_27.pdf",
                filename="budget_book_2026_27.pdf",
                format="pdf",
                mutable=True,
            )
        ]


class FakeSpend(Source):
    slug = "testville"
    name = "Testville"
    threshold = "£500"
    access = "scrape"
    landing_page = "https://example.invalid/spending"

    def discover(self, client, since, until):
        return [
            RemoteFile(
                borough=self.slug,
                period="2026-07",
                url="https://example.invalid/payments_july_2026.csv",
                filename="payments_july_2026.csv",
                format="csv",
            )
        ]


@pytest.fixture
def two_sources(monkeypatch, client_for):
    """Replace the registry with one spend source and one budget source.

    The real registry is 27 sources across the live internet; two fakes make
    what ``--kind`` selects readable at a glance.
    """
    # Rich folds a cell that does not fit, and the default width under pytest
    # is 80, which would split a slug across two lines mid-word.
    monkeypatch.setenv("COLUMNS", "200")
    sources = {"testville": FakeSpend(), "testville-budget": FakeBudget()}
    monkeypatch.setattr(cli, "iter_sources", lambda: list(sources.values()))
    monkeypatch.setattr(cli, "get_source", sources.get)

    body = {"pdf": BUDGET_BYTES, "csv": "supplier,amount\nAcme,100\n"}

    def handler(request: httpx.Request) -> httpx.Response:
        kind = "pdf" if request.url.path.endswith(".pdf") else "csv"
        return httpx.Response(200, text=body[kind], headers={"ETag": '"v1"'})

    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(handler))
    return sources


def test_list_defaults_to_spend_and_all_shows_both(two_sources, capsys, tmp_path):
    assert cli.main(["list", "--data-dir", str(tmp_path)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "testville" in out
    assert "testville-budget" not in out

    assert (
        cli.main(["list", "--kind", "all", "--data-dir", str(tmp_path)]) == cli.EXIT_OK
    )
    out = capsys.readouterr().out
    assert "testville-budget" in out
    # The kind column is what tells the two apart in one table.
    assert "budget" in out and "spend" in out


def test_list_kind_budget_shows_only_budget(two_sources, capsys, tmp_path):
    cli.main(["list", "--kind", "budget", "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "testville-budget" in out
    assert "£500" not in out


def test_download_all_respects_kind(two_sources, capsys, tmp_path):
    assert cli.main(["download", "--all", "--data-dir", str(tmp_path)]) == cli.EXIT_OK
    assert (tmp_path / "raw/testville/2026-07__payments_july_2026.csv").is_file()
    assert not (tmp_path / "budgets").exists()


def test_download_all_kind_budget_writes_to_the_budget_tree(
    two_sources, capsys, tmp_path
):
    code = cli.main(
        ["download", "--all", "--kind", "budget", "--data-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_OK
    written = (
        tmp_path / "budgets/testville-budget/2026-04_2027-03__budget_book_2026_27.pdf"
    )
    assert written.read_text() == BUDGET_BYTES
    assert not (tmp_path / "raw").exists()


def test_download_all_kind_all_writes_both_trees(two_sources, tmp_path):
    cli.main(["download", "--all", "--kind", "all", "--data-dir", str(tmp_path)])
    assert (tmp_path / "raw/testville/2026-07__payments_july_2026.csv").is_file()
    assert (
        tmp_path / "budgets/testville-budget/2026-04_2027-03__budget_book_2026_27.pdf"
    ).is_file()


def test_a_named_slug_works_whatever_kind_says(two_sources, tmp_path):
    """Typing the slug is already a choice of kind; the flag must not undo it."""
    code = cli.main(["download", "testville-budget", "--data-dir", str(tmp_path)])
    assert code == cli.EXIT_OK
    assert (
        tmp_path / "budgets/testville-budget/2026-04_2027-03__budget_book_2026_27.pdf"
    ).is_file()


def test_the_manifest_lands_beside_the_files_it_describes(two_sources, tmp_path):
    cli.main(["download", "--all", "--kind", "all", "--data-dir", str(tmp_path)])
    assert (tmp_path / "budgets/testville-budget/manifest.json").is_file()
    assert (tmp_path / "raw/testville/manifest.json").is_file()

    book = manifest.load(tmp_path, "testville-budget", "budget")
    entry = next(iter(book.entries.values()))
    assert entry.path.startswith("budgets/testville-budget/")
    assert book.kind == "budget"


def test_a_mutable_budget_file_is_rechecked_every_run(two_sources, capsys, tmp_path):
    """A budget book is republished in place when a figure is corrected."""
    argv = ["download", "testville-budget", "--data-dir", str(tmp_path)]
    assert cli.main(argv) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(argv) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert "0 already on disk" in err
    # Same bytes back, so it counts as skipped rather than as a download.
    assert "skipped=1" in err


def test_a_changed_mutable_budget_file_replaces_the_old_one(
    monkeypatch, client_for, two_sources, tmp_path
):
    state = {"body": BUDGET_BYTES}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=state["body"])

    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(handler))
    argv = ["download", "testville-budget", "--data-dir", str(tmp_path)]
    cli.main(argv)
    state["body"] = "%PDF-1.4 a corrected budget book\n"
    cli.main(argv)

    written = (
        tmp_path / "budgets/testville-budget/2026-04_2027-03__budget_book_2026_27.pdf"
    )
    assert written.read_text() == state["body"]
    assert len(list((tmp_path / "budgets/testville-budget").glob("*.pdf"))) == 1


def test_status_totals_only_the_kind_it_was_asked_for(two_sources, capsys, tmp_path):
    cli.main(["download", "--all", "--kind", "all", "--data-dir", str(tmp_path)])
    capsys.readouterr()

    cli.main(["status", "--data-dir", str(tmp_path)])
    assert "testville-budget" not in capsys.readouterr().out

    cli.main(["status", "--kind", "all", "--data-dir", str(tmp_path)])
    assert "testville-budget" in capsys.readouterr().out


def test_the_resume_hint_carries_the_kind(
    monkeypatch, client_for, two_sources, capsys, tmp_path
):
    """An interrupted ``--all --kind budget`` must resume as the same run."""

    def interrupt(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "make_client", lambda **_: client_for(interrupt))
    code = cli.main(
        ["download", "--all", "--kind", "budget", "--data-dir", str(tmp_path)]
    )
    assert code == cli.EXIT_INTERRUPTED
    err = capsys.readouterr().err
    assert "scrooge download --all --kind budget" in err
