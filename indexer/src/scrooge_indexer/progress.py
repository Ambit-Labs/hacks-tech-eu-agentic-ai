"""A Rich bar on a terminal, plain periodic stderr lines on a pipe.

Rich renders *nothing* through a pipe: ``Live`` skips every refresh when the
console is not a terminal. A download under cron would therefore be
byte-for-byte silent for its whole run, indistinguishable from a wedged
process. :class:`PlainProgress` implements the slice of the ``Progress`` API
this CLI uses and prints one line at a time instead, so the same code path
serves both. Modelled on ``firme.progress``, cut down to what one download
loop needs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

#: Seconds between plain stderr updates.
PLAIN_INTERVAL = 15.0

#: Totals at or below this print every step on the plain path instead of on
#: the timer. A five-file smoke run should say five things, not one.
STEPWISE_MAX_TOTAL = 40

#: Fields rendered as live outcome counters, in this order.
COUNTER_FIELDS = ("ok", "skipped", "failed")


def stderr_console() -> Console:
    """The one console this CLI prints progress to.

    stderr, always: stdout carries the tables a person may want to pipe into
    something else, and progress chatter must not land in that stream.
    """
    return Console(stderr=True)


def format_bytes(n: float) -> str:
    """``123B`` / ``4.2KB`` / ``7.8MB``, binary prefixes, no spaces."""
    if n < 1024:
        return f"{int(n)}B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f}{unit}"
    return f"{n:.1f}PB"


class CountersColumn(ProgressColumn):
    """``ok 12 · skipped 3 · failed 1 · 4.2MB`` from the task's fields.

    The outcome counters are the whole point of watching a download: a bar that
    only moves tells you nothing about whether the files are arriving or the
    council is 404-ing every month.
    """

    def render(self, task) -> Text:
        parts = [
            f"{name} {task.fields[name]}"
            for name in COUNTER_FIELDS
            if task.fields.get(name)
        ]
        got = task.fields.get("bytes") or 0
        if got:
            parts.append(format_bytes(got))
        return Text(" · ".join(parts), style="dim")


class ETAColumn(ProgressColumn):
    """Remaining time from the run's own average rate, not Rich's window.

    Rich's ``TimeRemainingColumn`` smooths over the last few samples, which on
    a download whose steps are a 2 KB skip and a 4 MB fetch swings wildly.
    Total done over total elapsed is duller and closer to the truth.
    """

    def render(self, task) -> Text:
        if not task.total or not task.completed or not task.elapsed:
            return Text("eta --:--", style="cyan")
        remaining = (task.total - task.completed) / (task.completed / task.elapsed)
        return Text(f"eta {timedelta(seconds=int(remaining))}", style="cyan")


def bar_columns() -> tuple:
    return (
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        CountersColumn(),
        TimeElapsedColumn(),
        ETAColumn(),
    )


@dataclass
class _PlainTask:
    description: str
    total: float | None
    started: float
    completed: float = 0.0
    last_emit: float = 0.0
    finished: bool = False
    fields: dict = field(default_factory=dict)


class PlainProgress:
    """Stand-in for :class:`rich.progress.Progress` when stderr is a pipe.

    One start line, then a line per step for a small total or one every
    ``interval`` seconds for a large one, then exactly one terminal line:
    ``done`` on a clean exit, ``stopped at`` when the block leaves on an
    exception, which is what a Ctrl-C looks like from here.
    """

    def __init__(
        self,
        console: Console,
        *,
        interval: float = PLAIN_INTERVAL,
        clock=time.monotonic,
    ) -> None:
        self._console = console
        self._interval = interval
        self._clock = clock
        self._tasks: list[_PlainTask] = []

    # -- Progress API ------------------------------------------------------ #

    def __enter__(self) -> PlainProgress:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        for task in self._tasks:
            if not task.finished:
                self._close(task, "stopped at" if exc_type else "done")
        return False

    def add_task(
        self, description: str, *, total: float | None = None, **fields
    ) -> int:
        now = self._clock()
        task = _PlainTask(description, total, started=now, last_emit=now, fields=fields)
        self._tasks.append(task)
        size = f"{int(total):,}" if total else "?"
        self._line(f"{description}: starting, {size} files{self._fields(task)}")
        return len(self._tasks) - 1

    def advance(self, task_id: int, advance: float = 1) -> None:
        task = self._tasks[task_id]
        self._set_completed(task, task.completed + advance)

    def update(
        self,
        task_id: int,
        *,
        completed: float | None = None,
        advance: float | None = None,
        total: float | None = None,
        **fields,
    ) -> None:
        task = self._tasks[task_id]
        if total is not None:
            task.total = total
        task.fields.update(fields)
        if advance is not None:
            self._set_completed(task, task.completed + advance)
        elif completed is not None:
            self._set_completed(task, completed)

    # -- internals --------------------------------------------------------- #

    def _set_completed(self, task: _PlainTask, completed: float) -> None:
        task.completed = completed
        if task.total and completed >= task.total:
            self._close(task, "done")
            return
        now = self._clock()
        stepwise = task.total is not None and task.total <= STEPWISE_MAX_TOTAL
        if stepwise or now - task.last_emit >= self._interval:
            task.last_emit = now
            self._emit(task, None)

    def _close(self, task: _PlainTask, state: str) -> None:
        task.finished = True
        self._emit(task, state)

    def _emit(self, task: _PlainTask, state: str | None) -> None:
        total = f"/{int(task.total):,}" if task.total else ""
        elapsed = timedelta(seconds=int(self._clock() - task.started))
        head = f"{task.description}: " + (f"{state} " if state else "")
        self._line(
            f"{head}{int(task.completed):,}{total}{self._fields(task)} in {elapsed}"
        )

    def _fields(self, task: _PlainTask) -> str:
        parts = [
            f"{name}={int(task.fields[name]):,}"
            for name in COUNTER_FIELDS
            if task.fields.get(name)
        ]
        got = task.fields.get("bytes") or 0
        if got:
            parts.append(f"bytes={format_bytes(got)}")
        return " · " + " ".join(parts) if parts else ""

    def _line(self, text: str) -> None:
        self._console.print(text, highlight=False, markup=False)


def make_progress(console: Console, *, interval: float = PLAIN_INTERVAL):
    """A Rich bar when ``console`` is a terminal, :class:`PlainProgress` when not.

    The one call the download loop makes, so "bar interactively, plain lines
    under cron" is a property of the toolkit rather than of each verb.
    """
    if console.is_terminal:
        return Progress(*bar_columns(), console=console, transient=False)
    return PlainProgress(console, interval=interval)
