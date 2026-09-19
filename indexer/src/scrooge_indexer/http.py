"""The HTTP half: one polite client, retries with backoff, atomic downloads.

Nothing in here pretends to be a browser. The User-Agent names the tool, there
is no proxy support, and a 403 or a bot challenge is recorded as a refusal and
skipped. A council that does not want this traffic gets to say no.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import CONNECT_TIMEOUT, DEFAULT_DELAY, READ_TIMEOUT, USER_AGENT
from .models import RemoteFile

CHUNK = 1 << 16
PARTIAL_SUFFIX = ".part"
MAX_TRIES = 4
BACKOFF = 2.0

#: Retried: the source is busy or the connection broke, not the request.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

#: Substrings that mark a challenge page rather than data. Checked only on an
#: HTML body served where a data file was expected.
CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "cf-browser-verification",
    "checking your browser",
    "enable javascript and cookies",
    "awswaf",
)


class FetchError(RuntimeError):
    """A fetch that did not produce a file. ``kind`` maps to a manifest status."""

    kind = "failed"


class NotPublished(FetchError):
    """404. The council has not published this period, which is not a failure."""

    kind = "missing"


class Blocked(FetchError):
    """403, or a bot challenge in place of the file. Recorded, never solved."""

    kind = "blocked"


@dataclass
class FetchResult:
    """What one successful fetch left on disk."""

    bytes: int
    sha256: str | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    status: str = "ok"
    """``ok`` for a file written, ``unchanged`` for a 304 on a mutable file."""


class PoliteTransport(httpx.BaseTransport):
    """Wraps a transport and spaces requests to the same host.

    A transport rather than an event hook so the delay also applies to the
    redirects httpx follows internally, and so tests can build a client with
    ``delay=0`` over ``httpx.MockTransport`` and never touch the clock.
    """

    def __init__(
        self,
        inner: httpx.BaseTransport,
        delay: float = DEFAULT_DELAY,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._delay = delay
        self._sleep = sleep
        self._clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._delay > 0:
            host = request.url.host
            with self._lock:
                previous = self._last.get(host)
                now = self._clock()
                wait = 0.0 if previous is None else self._delay - (now - previous)
                self._last[host] = now + max(wait, 0.0)
            if wait > 0:
                self._sleep(wait)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def make_client(
    *,
    delay: float = DEFAULT_DELAY,
    transport: httpx.BaseTransport | None = None,
    **kwargs,
) -> httpx.Client:
    """The client every borough is handed: honest UA, redirects, polite pacing."""
    inner = transport if transport is not None else httpx.HTTPTransport(retries=1)
    return httpx.Client(
        transport=PoliteTransport(inner, delay),
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        follow_redirects=True,
        **kwargs,
    )


def _retry_after(response: httpx.Response, fallback: float) -> float:
    """Honour a numeric ``Retry-After``, capped so one bad header cannot park us."""
    raw = response.headers.get("Retry-After", "")
    try:
        return min(float(raw), 120.0)
    except ValueError:
        return fallback


def _looks_like_challenge(response: httpx.Response, body: bytes) -> bool:
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        return False
    head = body[:4096].decode("utf-8", "replace").lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


def request_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_tries: int = MAX_TRIES,
    backoff: float = BACKOFF,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> httpx.Response:
    """One request, retried on 429/5xx and transport faults with exponential backoff.

    Raises :class:`Blocked` on 403 and :class:`NotPublished` on 404 without
    retrying either: both are answers, not faults, and repeating them only
    annoys the server.
    """
    last_error: Exception | None = None
    for attempt in range(max_tries):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last_error = exc
            if attempt == max_tries - 1:
                raise FetchError(f"{type(exc).__name__}: {exc}") from exc
            sleep(backoff * (2**attempt))
            continue
        if response.status_code == 403:
            raise Blocked(f"HTTP 403 for {url}")
        if response.status_code == 404:
            raise NotPublished(f"HTTP 404 for {url}")
        if response.status_code in RETRY_STATUS:
            last_error = FetchError(f"HTTP {response.status_code} for {url}")
            if attempt == max_tries - 1:
                raise last_error
            sleep(_retry_after(response, backoff * (2**attempt)))
            continue
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code} for {url}")
        return response
    raise FetchError(str(last_error))


class _Retryable(RuntimeError):
    """Internal marker for a status worth another try."""


def part_path(dest: Path) -> Path:
    """The in-flight sibling of ``dest``. Deleted on any failure, including Ctrl-C."""
    return dest.with_name(dest.name + PARTIAL_SUFFIX)


def download_to(
    client: httpx.Client,
    remote: RemoteFile,
    dest: Path,
    *,
    on_bytes: Callable[[int], None] | None = None,
    conditional: dict[str, str] | None = None,
    max_tries: int = MAX_TRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """Stream ``remote`` into ``dest`` through a ``.part`` file, then rename.

    The rename is the completion marker: ``os.replace`` is atomic on POSIX, so
    a crash or a Ctrl-C leaves either the previous ``dest`` or nothing at all,
    never a half file that a later run would trust. ``conditional`` carries
    ``If-None-Match`` / ``If-Modified-Since`` for a mutable source; a 304 comes
    back as ``status="unchanged"`` with ``dest`` untouched.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = part_path(dest)
    headers = dict(remote.headers or {})
    headers.update(conditional or {})
    digest = hashlib.sha256()
    written = 0

    attempt = 0
    while True:
        try:
            with client.stream(
                remote.method,
                remote.url,
                params=remote.params,
                headers=headers or None,
            ) as response:
                if response.status_code == 304:
                    return FetchResult(bytes=0, status="unchanged")
                if response.status_code == 403:
                    raise Blocked(f"HTTP 403 for {remote.url}")
                if response.status_code == 404:
                    raise NotPublished(f"HTTP 404 for {remote.url}")
                if response.status_code in RETRY_STATUS:
                    raise _Retryable(f"HTTP {response.status_code} for {remote.url}")
                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code} for {remote.url}")

                digest = hashlib.sha256()
                written = 0
                first = b""
                with open(part, "wb") as handle:
                    for chunk in response.iter_bytes(CHUNK):
                        if not first:
                            first = chunk
                        handle.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        if on_bytes:
                            on_bytes(len(chunk))
                if _looks_like_challenge(response, first):
                    raise Blocked(f"bot challenge served for {remote.url}")
                os.replace(part, dest)
                return FetchResult(
                    bytes=written,
                    sha256=digest.hexdigest(),
                    content_type=response.headers.get("Content-Type"),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
        except (_Retryable, httpx.TransportError) as exc:
            part.unlink(missing_ok=True)
            attempt += 1
            if attempt >= max_tries:
                raise FetchError(f"{type(exc).__name__}: {exc}") from exc
            sleep(BACKOFF * (2 ** (attempt - 1)))
        except BaseException:
            # Includes KeyboardInterrupt: an interrupted transfer leaves no
            # `.part` behind for the next run to puzzle over.
            part.unlink(missing_ok=True)
            raise


def host_of(url: str) -> str:
    return urlsplit(url).netloc
