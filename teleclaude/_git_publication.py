"""Confine one work-ref push while retaining Git's own lease/inclusion decision."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import signal
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from teleclaude.git import GIT_EXECUTABLE, publication_environment
from teleclaude.git_lock import main_branch_lock

_HEADS = "refs/heads/"
_TRACKING = "refs/remotes/origin/"
_UTF8 = "utf-8"
_ASCII = "ascii"
_NEWLINE = "\n"
_EMPTY = ""
_ZERO = "0" * 40
_SHA = re.compile(r"[0-9a-f]{40}")
_INVALID = "Publication requires faithful files-backed ref and reflog data"
_HOOK_OPTIONS = ("-c", "core.hooksPath=" + os.devnull)
_SOURCE_CONFIG = ("-c", "core.fsmonitor=false")
_GIT_TIMEOUT = 30
_REF_STORAGE = ("config", "--get", "extensions.refStorage")
_FILES = "files"
_REFLOG_ROOT = "logs/"
_HEAD = "HEAD"
_READ_HEAD = ("symbolic-ref", "--quiet", _HEAD)
_READ_COMMIT = ("rev-parse", "--verify", "HEAD^{commit}")
_COMMON = ("rev-parse", "--path-format=absolute", "--git-common-dir")
_OBJECTS = ("rev-parse", "--path-format=absolute", "--git-path", "objects")
_FETCH_MAP = "+{ref}:{tracking}"
_CONFIG = "config"
_REMOTE_URL = "remote.origin.url"
_REMOTE_FETCH = "remote.origin.fetch"
_HEAD_CONTENT = "ref: {ref}\n"
_DIRECTORY = "-C"
_SHOW_REF_EXISTS = ("show-ref", "--exists")
_REV_PARSE_REF = ("rev-parse", "--verify")
_CHECK_REF = "check-ref-format"
_ALTERNATES = "objects/info/alternates"
_ADD = "--add"
_UPDATE_REF = "update-ref"
_REPLACE = "replace"
_UP_TO_DATE = "="
_CONFIG_HELP = ("help", "--config")
_PROACTIVE_AUTH = "http.proactiveAuth"
_ORIGIN = "origin"
_PUSH = ("push", "--porcelain", "--force-if-includes", "--no-follow-tags", "--recurse-submodules=no")
_LEASE = "--force-with-lease={ref}"
_REFSPEC = "{ref}:{ref}"
_CONFINEMENT = {
    "core.hooksPath": os.devnull,
    "core.logAllRefUpdates": "false",
    "credential.helper": "",
    "credential.useHttpPath": "true",
    "protocol.allow": "never",
    "protocol.https.allow": "always",
    "http.sslVerify": "true",
    "http.followRedirects": "false",
    "http.proactiveAuth": "basic",
    "http.emptyAuth": "false",
    "http.maxRetries": "0",
    "push.followTags": "false",
    "push.recurseSubmodules": "no",
}
_HELPER = "!{binary} auth git-credential"
_HELPER_KEY = "credential.helper"
_INIT = ("init", "--bare", "--template=", "--object-format=sha1")
_ACK_FLAGS = frozenset({_EMPTY, " ", "+", "*", "=", "!", "-"})
_UPDATE_FLAGS = frozenset({" ", "+", "*"})
_TAB = "\t"


@dataclass(frozen=True)
class GitPushObservation:
    """Safe actual-child evidence; no raw output is exposed."""

    started: bool
    acknowledged: bool = False
    noop: bool = False
    successful: bool = False


class GitPushCancelled(asyncio.CancelledError):
    """Preserve available acknowledgment while leaving cancellation intact."""

    def __init__(self, observation: GitPushObservation) -> None:
        super().__init__()
        self.observation = observation


def _git(directory: Path, *arguments: str, allow_absent: bool = False, absent_code: int = 1) -> bytes | None:
    # Native Git owns ref/storage/reflog semantics; raw output never enters diagnostic logs.
    completed = subprocess.run(
        [GIT_EXECUTABLE, *_HOOK_OPTIONS, *_SOURCE_CONFIG, _DIRECTORY, str(directory), *arguments],
        env=publication_environment(),
        capture_output=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    if allow_absent and completed.returncode == absent_code:
        return None
    raise ValueError(_INVALID)


def _text(directory: Path, *arguments: str) -> str:
    value = _git(directory, *arguments)
    if value is None:
        raise ValueError(_INVALID)
    return value.decode(_UTF8).strip()


def _ref(directory: Path, ref: str) -> str | None:
    raw = _git(directory, *_SHOW_REF_EXISTS, ref, allow_absent=True, absent_code=2)
    if raw is None:
        return None
    value = _text(directory, *_REV_PARSE_REF, ref)
    if not _SHA.fullmatch(value):
        raise ValueError(_INVALID)
    return value


def _copy_log(source: Path, destination: Path, tip: str | None) -> bytes | None:
    if not source.exists():
        if tip is not None:
            raise ValueError(_INVALID)
        return None
    if source.is_symlink() or not source.is_file():
        raise ValueError(_INVALID)
    stamp = source.stat()
    content = source.read_bytes()
    lines = content.splitlines()
    if tip is not None and (not lines or len(lines[-1].split()) < 2 or lines[-1].split()[1] != tip.encode(_ASCII)):
        raise ValueError(_INVALID)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if (
        destination.read_bytes() != content
        or source.read_bytes() != content
        or source.stat().st_mtime_ns != stamp.st_mtime_ns
        or destination.stat().st_mtime_ns != stamp.st_mtime_ns
    ):
        raise ValueError(_INVALID)
    return content


@dataclass(frozen=True)
class WorkRefSnapshot:
    """Only named work/tracking refs and faithful logs; source configuration is never copied."""

    worktree: Path
    isolated: Path
    ref: str
    tracking: str
    head: str
    previous_tracking: str | None

    @classmethod
    def capture(cls, worktree: Path, isolated: Path, branch: str, head: str, base: str) -> WorkRefSnapshot:
        """Take a coherent source snapshot under the existing local commit coordination."""
        ref, tracking = _HEADS + branch, _TRACKING + branch
        with main_branch_lock():
            _git(worktree, _CHECK_REF, ref)
            _git(worktree, _CHECK_REF, _HEADS + base)
            if _PROACTIVE_AUTH not in _text(worktree, *_CONFIG_HELP).splitlines():
                raise ValueError(_INVALID)
            storage = _git(worktree, *_REF_STORAGE, allow_absent=True)
            if storage is not None and storage.decode(_ASCII).strip() != _FILES:
                raise ValueError(_INVALID)
            if branch == base or _text(worktree, *_READ_HEAD) != ref or _text(worktree, *_READ_COMMIT) != head:
                raise ValueError(_INVALID)
            common = Path(_text(worktree, *_COMMON))
            objects = _text(worktree, *_OBJECTS)
            if _NEWLINE in objects or not Path(objects).is_dir():
                raise ValueError(_INVALID)
            previous = _ref(worktree, tracking)
            _git(isolated.parent, *_INIT, str(isolated))
            (isolated / _HEAD).write_text(_HEAD_CONTENT.format(ref=ref), encoding=_ASCII)
            for name, value in ((ref, head), (tracking, previous)):
                if value is not None:
                    destination = isolated / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(value + _NEWLINE, encoding=_ASCII)
            alternates = isolated / _ALTERNATES
            alternates.write_text(objects + _NEWLINE, encoding=_UTF8)
            work_log = _copy_log(common / (_REFLOG_ROOT + ref), isolated / (_REFLOG_ROOT + ref), head)
            tracking_log = _copy_log(common / (_REFLOG_ROOT + tracking), isolated / (_REFLOG_ROOT + tracking), previous)
            if (
                _text(worktree, *_READ_HEAD) != ref
                or _text(worktree, *_READ_COMMIT) != head
                or _ref(worktree, tracking) != previous
                or (common / (_REFLOG_ROOT + ref)).read_bytes() != work_log
                or (tracking_log is not None and (common / (_REFLOG_ROOT + tracking)).read_bytes() != tracking_log)
                or (tracking_log is None and (common / (_REFLOG_ROOT + tracking)).exists())
            ):
                raise ValueError(_INVALID)
        return cls(worktree, isolated, ref, tracking, head, previous)

    def configure(self, repository_url: str, gh: Path) -> None:
        """Only this canonical transport and fixed native helper can authenticate the child."""
        for name, value in _CONFINEMENT.items():
            _git(self.isolated, _CONFIG, name, value)
        _git(self.isolated, _CONFIG, _ADD, _HELPER_KEY, _HELPER.format(binary=shlex.quote(str(gh))))
        _git(self.isolated, _CONFIG, _REMOTE_URL, repository_url)
        _git(self.isolated, _CONFIG, _REMOTE_FETCH, _FETCH_MAP.format(ref=self.ref, tracking=self.tracking))

    def unchanged(self) -> bool:
        """Check the captured source is still the committed branch; never change the requested head."""
        with main_branch_lock():
            common = Path(_text(self.worktree, *_COMMON))
            if (
                _text(self.worktree, *_READ_HEAD) != self.ref
                or _text(self.worktree, *_READ_COMMIT) != self.head
                or _ref(self.worktree, self.tracking) != self.previous_tracking
            ):
                return False
            for name in (self.ref, self.tracking):
                source, captured = common / (_REFLOG_ROOT + name), self.isolated / (_REFLOG_ROOT + name)
                if source.exists() != captured.exists():
                    return False
                if captured.exists() and (
                    source.read_bytes() != captured.read_bytes()
                    or source.stat().st_mtime_ns != captured.stat().st_mtime_ns
                ):
                    return False
            return True

    def advance_tracking(self) -> bool:
        """Conditional tokenless metadata progression cannot overwrite a concurrent source writer."""
        try:
            with main_branch_lock():
                _git(self.worktree, _UPDATE_REF, self.tracking, self.head, self.previous_tracking or _ZERO)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        return True


def _observation(started: bool, code: int | None, stdout: bytes, ref: str) -> GitPushObservation:
    rows = [line.split(_TAB) for line in stdout.decode(_UTF8, errors=_REPLACE).splitlines() if _TAB in line]
    if len(rows) != 1 or len(rows[0]) != 3:
        return GitPushObservation(started)
    flag, refspec, _ = rows[0]
    if flag not in _ACK_FLAGS or refspec != _REFSPEC.format(ref=ref):
        return GitPushObservation(started)
    return GitPushObservation(
        started,
        acknowledged=flag in _UPDATE_FLAGS,
        noop=flag == _UP_TO_DATE and code == 0,
        successful=code == 0,
    )


async def push_snapshot(snapshot: WorkRefSnapshot, environment: Mapping[str, str]) -> GitPushObservation:
    """Attempt exactly one native push, preserving recovered output on cancellation."""
    # Git's real transport and inclusion implementation are required; no Python substitute is equivalent.
    launch = asyncio.create_task(
        asyncio.create_subprocess_exec(
            GIT_EXECUTABLE,
            *_HOOK_OPTIONS,
            _DIRECTORY,
            str(snapshot.isolated),
            *_PUSH,
            _LEASE.format(ref=snapshot.ref),
            _ORIGIN,
            _REFSPEC.format(ref=snapshot.ref),
            env=environment,
            start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    )
    try:
        process = await asyncio.shield(launch)
    except OSError:
        return GitPushObservation(False)
    except asyncio.CancelledError:
        try:
            process = await launch
        except OSError:
            raise GitPushCancelled(GitPushObservation(False)) from None
        raise GitPushCancelled(await _settle(process, snapshot.ref)) from None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=_GIT_TIMEOUT)
    except asyncio.CancelledError:
        raise GitPushCancelled(await _settle(process, snapshot.ref)) from None
    except (TimeoutError, OSError):
        return await _settle(process, snapshot.ref)
    return _observation(True, process.returncode, stdout, snapshot.ref)


async def _settle(process: asyncio.subprocess.Process, ref: str) -> GitPushObservation:
    try:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        stdout, _ = await process.communicate()
    except OSError:
        await process.wait()
        return GitPushObservation(True)
    return _observation(True, process.returncode, stdout, ref)
