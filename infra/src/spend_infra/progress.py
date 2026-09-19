"""A Rich spinner on a terminal, plain periodic stderr lines on a pipe.

Rich renders nothing through a pipe: ``Live`` skips every refresh when the
console is not a terminal, so a ``pg start`` under cron would be silent for
the two minutes the image takes to build. :class:`Waiter` presents one API
and picks the renderer from ``console.is_terminal``.

Same split as ``spend_indexer.progress``, narrowed to the one shape this CLI
needs: these waits have no total to count against, only elapsed time and a
line of status.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import timedelta

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

#: Seconds between plain stderr updates when stderr is not a tty.
PLAIN_INTERVAL = 15.0


def stderr_console() -> Console:
    """The one console this CLI prints progress to.

    stderr, always: stdout carries the URL that a shell substitution captures
    and the table a person may pipe elsewhere, and neither may pick up a
    spinner frame.
    """
    return Console(stderr=True)


def out_console() -> Console:
    """stdout, for results a caller may want to capture.

    ``soft_wrap`` is on because rich otherwise folds any line longer than the
    terminal width, 80 columns when stdout is a pipe. A connection URL with a
    32 character password is longer than that, and ``$(pg url)`` would carry a
    newline in the middle of the database name. Markup and highlighting are
    off for the same reason: a password can contain ``[``.
    """
    return Console(soft_wrap=True, markup=False, highlight=False)


class Waiter:
    """A running wait, with a status line that can be replaced as it goes."""

    def __init__(self, console: Console, description: str, *, interval: float):
        self._console = console
        self._description = description
        self._interval = interval
        self._clock = time.monotonic
        self._started = self._clock()
        self._last_emit = self._started
        self._status = ""
        self._progress: Progress | None = None
        self._task_id: int | None = None

    # -- lifecycle --------------------------------------------------------- #

    def _start(self) -> None:
        if self._console.is_terminal:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                TextColumn("{task.fields[status]}", style="dim"),
                TimeElapsedColumn(),
                console=self._console,
                transient=True,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(
                self._description, total=None, status=""
            )
        else:
            self._line(f"{self._description}: starting")

    def _stop(self, outcome: str) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
        self._line(f"{self._description}: {outcome} in {self.elapsed_text}")

    # -- API used by the verbs --------------------------------------------- #

    def update(self, status: str) -> None:
        """Replace the status text. Cheap enough to call in a poll loop."""
        self._status = status
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, status=status)
            return
        now = self._clock()
        if now - self._last_emit >= self._interval:
            self._last_emit = now
            self._line(f"{self._description}: {status} after {self.elapsed_text}")

    def note(self, text: str) -> None:
        """Print a line that survives the spinner, for a one-off event."""
        if self._progress is not None:
            self._progress.console.print(text, highlight=False, markup=False)
        else:
            self._line(text)

    @property
    def elapsed(self) -> float:
        return self._clock() - self._started

    @property
    def elapsed_text(self) -> str:
        return str(timedelta(seconds=int(self.elapsed)))

    def _line(self, text: str) -> None:
        self._console.print(text, highlight=False, markup=False)


@contextmanager
def waiting(console: Console, description: str, *, interval: float = PLAIN_INTERVAL):
    """Run a block under a spinner, and say how it ended either way.

    A clean exit prints ``done``, an exception prints ``stopped after``, so a
    Ctrl-C during a five minute cold start leaves a record of how far it got
    rather than a bare traceback.
    """
    waiter = Waiter(console, description, interval=interval)
    waiter._start()
    try:
        yield waiter
    except BaseException:
        waiter._stop("stopped")
        raise
    else:
        waiter._stop("done")
