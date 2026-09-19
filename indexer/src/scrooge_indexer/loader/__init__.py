"""Reading the spend files on disk into Postgres.

Five pieces, in the order a file passes through them: `mappings` says which
published column is which typed column, `readers` turns the bytes into a
header and a row stream, `values` decides whether a cell is usable, `rows`
builds the tuples, and `db` writes them. `runner` is the file-at-a-time glue
and `files` is the walk over data/raw.

The contract is docs/payments-schema.md and docs/payments-schema.sql. Nothing
here invents a column name or a value rule that is not in one of those two,
except where a real file on disk needed a spelling the doc does not list, and
every one of those carries a comment saying which borough it came from.
"""

from __future__ import annotations

from .db import DatabaseUnavailable
from .mappings import SPEND_BOROUGHS

__all__ = ["SPEND_BOROUGHS", "DatabaseUnavailable"]
