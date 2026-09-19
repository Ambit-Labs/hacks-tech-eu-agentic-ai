"""Shared fixtures. Nothing in this suite touches the network."""

from __future__ import annotations

import httpx
import pytest

from scrooge_indexer.http import make_client


@pytest.fixture
def client_for():
    """Build a real client, with the project's headers, over a mocked transport.

    ``delay=0`` so the politeness pacing never sleeps in tests: the pacing
    itself is tested directly in ``test_http.py``.
    """
    opened: list[httpx.Client] = []

    def _make(handler) -> httpx.Client:
        client = make_client(delay=0, transport=httpx.MockTransport(handler))
        opened.append(client)
        return client

    yield _make
    for client in opened:
        client.close()
