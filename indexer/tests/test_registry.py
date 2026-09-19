"""The registry finds boroughs by scanning the package, with no shared list."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from scrooge_indexer import boroughs
from scrooge_indexer.boroughs import base

PACKAGE_DIR = Path(base.__file__).parent

NEW_BOROUGH = '''
"""A borough added by dropping one file into the package."""

from __future__ import annotations

from .base import Source


class Testville(Source):
    slug = "testville"
    name = "Testville"
    threshold = "£250"
    access = "scrape"
    landing_page = "https://example.invalid/spending"

    def discover(self, client, since, until):
        return []
'''

BROKEN_BOROUGH = "raise RuntimeError('this module is broken')\n"


@pytest.fixture
def drop_module():
    """Write a module into the boroughs package, then take it away again."""
    written: list[Path] = []

    def _drop(name: str, body: str) -> Path:
        path = PACKAGE_DIR / f"{name}.py"
        path.write_text(body, encoding="utf-8")
        written.append(path)
        # The import machinery caches directory listings by mtime, and a file
        # written and imported within the same second would otherwise be missed.
        importlib.invalidate_caches()
        return path

    yield _drop
    for path in written:
        path.unlink(missing_ok=True)
    importlib.invalidate_caches()
    boroughs.registry(refresh=True)


def test_the_three_reference_boroughs_are_registered():
    slugs = boroughs.all_slugs()
    assert {"camden", "richmond", "wandsworth"} <= set(slugs)
    assert slugs == sorted(slugs)


def test_each_source_declares_the_full_interface():
    for source in boroughs.iter_sources():
        assert source.slug and source.slug.islower()
        assert source.name
        assert source.threshold
        assert source.access
        assert source.landing_page.startswith("https://")
        assert callable(source.discover)


def test_the_shared_umbraco_base_is_not_itself_a_borough():
    """Richmond and Wandsworth share a class. It must not register as a fourth."""
    assert "_umbraco" not in boroughs.all_slugs()
    assert "base" not in boroughs.all_slugs()


def test_adding_one_file_adds_a_borough(drop_module):
    drop_module("testville", NEW_BOROUGH)
    registry = boroughs.registry(refresh=True)
    assert "testville" in registry
    assert registry["testville"].name == "Testville"
    assert registry["testville"].threshold == "£250"


def test_a_broken_module_is_reported_and_the_rest_still_load(drop_module):
    drop_module("brokenville", BROKEN_BOROUGH)
    registry = boroughs.registry(refresh=True)
    assert "camden" in registry
    assert [name for name, _ in boroughs.import_errors()] == ["brokenville"]


def test_get_source_returns_none_for_an_unknown_slug():
    assert boroughs.get_source("atlantis") is None
