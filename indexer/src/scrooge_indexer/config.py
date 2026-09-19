"""Where the raw files land, and how politely we ask for them.

One resolver (:func:`resolve_data_dir`) rather than a settings object: the only
thing the whole CLI has to agree on is the data directory, and a function keeps
the precedence order (flag, env, repo default) readable in one place.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_DATA_DIR = "SCROOGE_DATA_DIR"

#: Sent on every request. Honest about what the tool is and where it came from,
#: because the alternative (a copied browser string) is exactly the evasion this
#: project refuses to do. A council that wants to block us must be able to.
USER_AGENT = "scrooge-indexer/0.1 (+research; contact via repo)"

#: Seconds to wait between two requests to the same host. Councils serve these
#: files from ordinary CMS boxes, and a monthly backfill is ~90 files per
#: borough, so the default is slow on purpose.
DEFAULT_DELAY = 0.5

#: Per-request timeouts. Connect is short (a dead host should fail fast), read
#: is long: Redbridge serves ~10 MB monthly CSVs and Socrata takes its time on
#: a 50,000-row page.
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 120.0

_DOTENV_NAMES = (".env", ".env.local")
_dotenv_loaded = False


def repo_root(start: Path | None = None) -> Path | None:
    """The nearest ancestor of ``start`` holding a ``.git`` directory.

    Walking up from this file rather than from the process cwd: the data
    directory has to be the same folder whether the CLI was run from
    ``indexer/``, from the repo root, or from a cron line with no cwd at all.
    """
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").is_dir():
            return candidate
    return None


def load_env(start: Path | None = None) -> None:
    """Load ``.env`` then ``.env.local`` from the repo root, once per process.

    ``override=False`` throughout, so a variable already exported in the shell
    or set by a cron line always wins over a file. ``.env.local`` is read second
    but cannot override ``.env`` either, matching python-dotenv's usual
    first-wins behaviour.
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    root = repo_root(start)
    if root is None:
        return
    for name in _DOTENV_NAMES:
        path = root / name
        if path.is_file():
            load_dotenv(path, override=False)


def resolve_data_dir(override: str | Path | None = None) -> Path:
    """``--data-dir PATH`` then ``$SCROOGE_DATA_DIR`` then ``<repo>/data``.

    Falls back to ``./data`` when the package is installed outside a checkout,
    which is the only case where there is no repo root to anchor to.
    """
    if override is not None:
        return Path(override).expanduser()
    load_env()
    env_value = os.environ.get(ENV_DATA_DIR)
    if env_value:
        return Path(env_value).expanduser()
    root = repo_root()
    return (root / "data") if root else Path("data")


#: Top-level directory per source kind. Spend files keep the ``raw/`` tree they
#: have always had, so nothing already on disk moves; budgets get their own
#: tree because a budget book and a payment list answer different questions and
#: a later stage should never have to tell them apart by filename.
KIND_DIRS = {"spend": "raw", "budget": "budgets"}


def kind_dir(data_dir: Path, kind: str) -> Path:
    """``<data>/raw`` or ``<data>/budgets``."""
    return Path(data_dir) / KIND_DIRS[kind]


def raw_dir(data_dir: Path, slug: str, kind: str = "spend") -> Path:
    """Where one source's untouched files live: ``<data>/<tree>/<slug>``."""
    return kind_dir(data_dir, kind) / slug
