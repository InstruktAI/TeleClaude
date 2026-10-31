"""Complete hang dumps for the API watch.

A dump answers where each overdue request is waiting: the complete stack of
every thread and the await chain of every pending event-loop task, with each
task that serves an overdue request labelled with that request.

The work is split at the event-loop boundary. ``capture_hang_state`` runs on the
loop thread, because coroutine state changes whenever the loop runs, and reads
only frame attributes: it touches no file and no ``linecache`` entry.
``write_hang_dump`` runs source lookup, formatting, publication and retention on
a worker thread owned by this module, so a persisting dump never holds the loop
that serves requests, and still works when the loop's default executor is
exhausted.

A dump is written beside its final name and renamed into place, so a file under
its final name is always complete. Variable values, request content and object
reprs are never recorded.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import traceback
import types
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import resolve_log_file

# One code location: filename, line number, function name.
type FrameLocation = tuple[str, int, str]

# Request id of the request the current task serves; written by the request-tracking middleware only.
INFLIGHT_REQUEST: ContextVar[int | None] = ContextVar("api_inflight_request", default=None)

# Number of dump files retained in the dump directory.
KEEP = 20

_persist_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hang-dump")


@dataclass(frozen=True)
class OverdueRequest:
    """A request in flight past the watch's threshold."""

    request_id: int
    method: str
    path: str
    age_s: float


@dataclass(frozen=True)
class ThreadStack:
    """The complete stack of one thread, outermost frame first."""

    name: str
    ident: int
    daemon: bool | None
    frames: tuple[FrameLocation, ...]


@dataclass(frozen=True)
class TaskChain:
    """The await chain of one pending task, outermost frame first, and what it waits on."""

    name: str
    coroutine: str
    request_id: int | None
    frames: tuple[FrameLocation, ...]
    awaiting: str | None


@dataclass(frozen=True)
class HangSnapshot:
    """Everything a dump records, read at one moment on the loop thread."""

    reason: str
    captured_at: datetime
    pid: int
    overdue: tuple[OverdueRequest, ...]
    threads: tuple[ThreadStack, ...]
    tasks: tuple[TaskChain, ...]


@dataclass(frozen=True)
class HangDumpResult:
    """A published dump."""

    path: Path
    threads: int
    tasks: int


def hang_dump_dir() -> Path:
    """Return the dump directory, beside the daemon's log files."""
    return resolve_log_file("teleclaude").parent / "hang-dumps"


def _location(frame: types.FrameType) -> FrameLocation:
    return (frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name)


def _thread_frames(frame: types.FrameType | None) -> tuple[FrameLocation, ...]:
    frames: list[FrameLocation] = []
    while frame is not None:
        frames.append(_location(frame))
        frame = frame.f_back
    frames.reverse()
    return tuple(frames)


def _describe_awaited(awaited: object) -> str:
    if isinstance(awaited, asyncio.Task):
        return f"Task {awaited.get_name()}"
    return type(awaited).__qualname__


def _await_chain(coro: object) -> tuple[tuple[FrameLocation, ...], str | None]:
    """Walk a suspended coroutine inward through everything it awaits.

    Returns the frames of the awaiting coroutines, outermost first, and a
    description of the object the innermost one waits on (None when it waits on
    nothing).
    """
    frames: list[FrameLocation] = []
    current: object | None = coro
    while current is not None:
        if isinstance(current, types.CoroutineType):
            frame, awaited = current.cr_frame, current.cr_await
        elif isinstance(current, types.AsyncGeneratorType):
            frame, awaited = current.ag_frame, current.ag_await
        elif isinstance(current, types.GeneratorType):
            frame, awaited = current.gi_frame, current.gi_yieldfrom
        else:
            return tuple(frames), _describe_awaited(current)
        if frame is not None:
            frames.append(_location(frame))
        current = awaited
    return tuple(frames), None


def _capture_threads() -> tuple[ThreadStack, ...]:
    known = {thread.ident: thread for thread in threading.enumerate()}
    stacks: list[ThreadStack] = []
    for ident, frame in sys._current_frames().items():  # CPython API for every thread's frame, uncapped
        thread = known.get(ident)
        stacks.append(
            ThreadStack(
                name=thread.name if thread is not None else "<unknown>",
                ident=ident,
                daemon=thread.daemon if thread is not None else None,
                frames=_thread_frames(frame),
            )
        )
    return tuple(sorted(stacks, key=lambda stack: (stack.name, stack.ident)))


def _capture_tasks(overdue_ids: frozenset[int]) -> tuple[TaskChain, ...]:
    chains: list[TaskChain] = []
    for task in asyncio.all_tasks():
        if task.done():
            continue
        request_id = task.get_context().get(INFLIGHT_REQUEST)
        coro = task.get_coro()
        frames, awaiting = _await_chain(coro)
        chains.append(
            TaskChain(
                name=task.get_name(),
                coroutine=coro.__qualname__ if isinstance(coro, types.CoroutineType) else type(coro).__qualname__,
                request_id=request_id if request_id in overdue_ids else None,
                frames=frames,
                awaiting=awaiting,
            )
        )
    return tuple(sorted(chains, key=lambda chain: (chain.request_id is None, chain.name)))


def capture_hang_state(reason: str, overdue: Sequence[OverdueRequest]) -> HangSnapshot:
    """Read every thread's stack and every pending task's await chain.

    Must run on the event-loop thread, so that threads and tasks describe the
    same moment. Reads frame attributes only: no file access and no
    ``linecache`` entry.
    """
    return HangSnapshot(
        reason=reason,
        captured_at=datetime.now(UTC),
        pid=os.getpid(),
        overdue=tuple(overdue),
        threads=_capture_threads(),
        tasks=_capture_tasks(frozenset(request.request_id for request in overdue)),
    )


def _format_frames(frames: tuple[FrameLocation, ...]) -> str:
    summary = traceback.StackSummary.from_list(
        [(filename, line, function, None) for filename, line, function in frames]
    )
    return "".join(summary.format())


def _render(snapshot: HangSnapshot) -> str:
    overdue_by_id = {request.request_id: request for request in snapshot.overdue}
    lines = [
        "API HANG DUMP",
        f"reason: {snapshot.reason}",
        f"time: {snapshot.captured_at.isoformat()}",
        f"pid: {snapshot.pid}",
        f"overdue requests: {len(snapshot.overdue)}",
    ]
    lines.extend(
        f"  #{request.request_id} {request.method} {request.path} age={request.age_s:.2f}s"
        for request in sorted(snapshot.overdue, key=lambda request: request.age_s, reverse=True)
    )
    lines.append("")
    lines.append(f"== Threads ({len(snapshot.threads)}) ==")
    for stack in snapshot.threads:
        lines.append(f"--- Thread {stack.name} ident={stack.ident} daemon={stack.daemon} ---")
        lines.append(_format_frames(stack.frames).rstrip("\n"))
    lines.append("")
    lines.append(f"== Pending tasks ({len(snapshot.tasks)}) ==")
    for chain in snapshot.tasks:
        label = ""
        if chain.request_id is not None:
            request = overdue_by_id[chain.request_id]
            label = f" serves overdue request #{request.request_id} {request.method} {request.path}"
        lines.append(f"--- Task {chain.name} coroutine={chain.coroutine}{label} ---")
        lines.append(_format_frames(chain.frames).rstrip("\n"))
        lines.append(f"  awaiting: {chain.awaiting if chain.awaiting is not None else 'nothing'}")
    return "\n".join(lines) + "\n"


def _persist(directory: Path, snapshot: HangSnapshot) -> HangDumpResult:
    """Render the snapshot, publish it under its final name and apply retention."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.captured_at.strftime("%Y%m%dT%H%M%S%fZ")
    final = directory / f"api-hang-{stamp}.txt"
    partial = directory / f".api-hang-{stamp}.partial"
    text = _render(snapshot)
    try:
        with partial.open("w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(partial, final)
    except OSError:
        with suppress(OSError):
            partial.unlink(missing_ok=True)
        raise
    for stale in sorted(directory.glob("api-hang-*.txt"))[:-KEEP]:
        stale.unlink(missing_ok=True)
    for leftover in directory.glob(".api-hang-*.partial"):
        leftover.unlink(missing_ok=True)
    return HangDumpResult(path=final, threads=len(snapshot.threads), tasks=len(snapshot.tasks))


async def write_hang_dump(directory: Path, snapshot: HangSnapshot) -> HangDumpResult:
    """Persist a captured snapshot on the module's worker thread.

    Returns once the dump is in place under its final name and retention has run.
    An ``OSError`` from the filesystem propagates.
    """
    return await asyncio.get_running_loop().run_in_executor(_persist_executor, _persist, directory, snapshot)
