"""The borough registry: every module in this package, found automatically.

Adding a borough must not mean editing a list. Several people extend this
package at the same time and a shared registry file would be a merge conflict
on every pull request, so the registry is a directory scan instead: drop
``hackney.py`` in here with a :class:`~.base.Source` subclass in it and
``spend list`` shows Hackney.

A module that fails to import is reported, not fatal. One contributor's typo
should not stop the other thirty boroughs from downloading.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from .base import Source

#: Modules in this package that are not boroughs.
_NOT_BOROUGHS = frozenset({"base"})

_sources: dict[str, Source] | None = None
_errors: list[tuple[str, Exception]] = []


def _collect(module) -> list[Source]:
    """Sources a module contributes: its ``SOURCE``, or the classes it defines.

    ``SOURCE`` wins when present, for a module that wants to register one
    configured instance of a shared class. Otherwise every concrete
    :class:`Source` subclass *defined in that module* counts, so a file can
    register more than one borough, and an abstract base shared by two files
    (Richmond and Wandsworth run the same CMS) registers neither.
    """
    declared = getattr(module, "SOURCE", None)
    if declared is not None:
        instance = declared() if inspect.isclass(declared) else declared
        return [instance]
    found = []
    for _, obj in vars(module).items():
        if not inspect.isclass(obj) or not issubclass(obj, Source) or obj is Source:
            continue
        if obj.__module__ != module.__name__ or inspect.isabstract(obj):
            continue
        if not getattr(obj, "slug", None):
            continue
        found.append(obj())
    return found


def _discover() -> dict[str, Source]:
    sources: dict[str, Source] = {}
    _errors.clear()
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_") or info.name in _NOT_BOROUGHS:
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
            for source in _collect(module):
                sources[source.slug] = source
        except Exception as exc:  # noqa: BLE001 - one bad module, not one bad run
            _errors.append((info.name, exc))
    return dict(sorted(sources.items()))


def registry(*, refresh: bool = False) -> dict[str, Source]:
    """``{slug: source}`` for every borough module, imported once per process."""
    global _sources
    if _sources is None or refresh:
        _sources = _discover()
    return _sources


def iter_sources(*, refresh: bool = False) -> list[Source]:
    return list(registry(refresh=refresh).values())


def get_source(slug: str) -> Source | None:
    return registry().get(slug)


def all_slugs() -> list[str]:
    return list(registry())


def import_errors() -> list[tuple[str, Exception]]:
    """Modules that failed to import during the last discovery pass."""
    registry()
    return list(_errors)


__all__ = [
    "Source",
    "all_slugs",
    "get_source",
    "import_errors",
    "iter_sources",
    "registry",
]
