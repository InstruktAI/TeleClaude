"""Data-driven matching for daemon-owned leaked process signatures."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import psutil

from teleclaude.core import db_models


class MatchReason(StrEnum):
    """Reasons the janitor may consider a process reapable."""

    SIGNATURE_TTL_EXPIRED = "signature_ttl_expired"
    EXPIRED_LEASE = "expired_lease"
    WOULD_REAP = "would_reap"


class MatcherKind(StrEnum):
    """Supported data-driven process signature matcher kinds."""

    PROCESS_SIGNATURE = "process_signature"


@dataclass(frozen=True)
class ProcessDescriptor:
    """Stable process-table facts used by signature policies."""

    pid: int
    ppid: int
    create_time: float
    cmdline: tuple[str, ...]
    uid: int

    @property
    def age_seconds(self) -> float:
        """Return process age in seconds."""
        return max(0.0, datetime.now(UTC).timestamp() - self.create_time)


@dataclass(frozen=True)
class ProcessJanitorPolicy:
    """Runtime policy row consumed by the matcher."""

    signature_id: str
    name: str
    matcher_kind: MatcherKind
    matcher_params: dict[str, object]
    ttl_seconds: int
    dry_run: bool

    @classmethod
    def from_row(cls, row: db_models.ProcessJanitorPolicy) -> ProcessJanitorPolicy:
        """Build a runtime policy from a database row."""
        parsed = json.loads(row.matcher_params_json or "{}")
        if not isinstance(parsed, dict):
            raise ValueError(f"Policy {row.signature_id} matcher params must be a JSON object")
        return cls(
            signature_id=row.signature_id,
            name=row.name,
            matcher_kind=MatcherKind(row.matcher_kind),
            matcher_params=parsed,
            ttl_seconds=row.ttl_seconds,
            dry_run=bool(row.dry_run),
        )


@dataclass(frozen=True)
class ProcessMatch:
    """A process that matched a reapable signature."""

    process: ProcessDescriptor
    policy: ProcessJanitorPolicy
    reason: MatchReason = MatchReason.SIGNATURE_TTL_EXPIRED
    owner: str | None = None
    lease_expires_at: str | None = None

    @property
    def pid(self) -> int:
        """Return the matched process id."""
        return self.process.pid


def default_policy_specs(default_ttl_seconds: int, *, dry_run_default: bool) -> list[dict[str, object]]:
    """Return seed policies for known TeleClaude leak classes."""
    return [
        {
            "signature_id": "execnet-pytest-xdist-orphan",
            "name": "execnet / pytest-xdist bootstrap orphan",
            "matcher_kind": MatcherKind.PROCESS_SIGNATURE.value,
            "matcher_params_json": json.dumps(
                {
                    "ppid": 1,
                    "any_cmdline_tokens": ["execnet", "pytest-xdist", "xdist"],
                }
            ),
            "ttl_seconds": default_ttl_seconds,
            "dry_run": dry_run_default,
        },
        {
            "signature_id": "stale-telec-tail-loop",
            "name": "stale telec sessions tail loop",
            "matcher_kind": MatcherKind.PROCESS_SIGNATURE.value,
            "matcher_params_json": json.dumps(
                {
                    "all_cmdline_tokens": ["telec", "sessions", "tail"],
                }
            ),
            "ttl_seconds": default_ttl_seconds,
            "dry_run": dry_run_default,
        },
        {
            "signature_id": "parentless-project-language-server",
            "name": "parentless node / pyright project server",
            "matcher_kind": MatcherKind.PROCESS_SIGNATURE.value,
            "matcher_params_json": json.dumps(
                {
                    "ppid": 1,
                    "executable_names": ["node", "pyright"],
                    "any_cmdline_tokens": [".venv", "pyright"],
                }
            ),
            "ttl_seconds": default_ttl_seconds,
            "dry_run": dry_run_default,
        },
        {
            "signature_id": "unregistered-chiptunes-worker",
            "name": "unregistered detached chiptunes worker",
            "matcher_kind": MatcherKind.PROCESS_SIGNATURE.value,
            "matcher_params_json": json.dumps(
                {
                    "all_cmdline_tokens": ["-m", "teleclaude.chiptunes.worker"],
                    "requires_unregistered": True,
                }
            ),
            "ttl_seconds": default_ttl_seconds,
            "dry_run": dry_run_default,
        },
    ]


def load_process_table() -> list[ProcessDescriptor]:
    """Read the host process table into immutable descriptors."""
    rows: list[ProcessDescriptor] = []
    own_uid = os.getuid()
    for proc in psutil.process_iter(["pid", "ppid", "create_time", "cmdline"]):
        try:
            uid = int(proc.uids().real)
            if uid != own_uid:
                continue
            rows.append(
                ProcessDescriptor(
                    pid=int(proc.info["pid"]),
                    ppid=int(proc.info["ppid"]),
                    create_time=float(proc.info["create_time"]),
                    cmdline=tuple(str(part) for part in (proc.info["cmdline"] or [])),
                    uid=uid,
                )
            )
        except (KeyError, TypeError, ValueError, psutil.Error):
            continue
    return rows


def match_processes(
    processes: list[ProcessDescriptor],
    policies: list[ProcessJanitorPolicy],
    *,
    registered_pids: set[int],
) -> list[ProcessMatch]:
    """Return process matches whose signature TTL has elapsed."""
    matches: list[ProcessMatch] = []
    for process in processes:
        for policy in policies:
            if process.age_seconds < policy.ttl_seconds:
                continue
            if _matches_policy(process, policy, registered_pids=registered_pids):
                matches.append(ProcessMatch(process=process, policy=policy))
    return matches


def _matches_policy(process: ProcessDescriptor, policy: ProcessJanitorPolicy, *, registered_pids: set[int]) -> bool:
    if policy.matcher_kind is not MatcherKind.PROCESS_SIGNATURE:
        raise ValueError(f"Unsupported process matcher kind: {policy.matcher_kind}")
    params = policy.matcher_params
    if _int_param(params, "ppid") is not None and process.ppid != _int_param(params, "ppid"):
        return False
    if _bool_param(params, "requires_unregistered") and process.pid in registered_pids:
        return False
    executable_names = _string_list(params.get("executable_names"))
    if executable_names and _executable_name(process.cmdline) not in set(executable_names):
        return False
    all_tokens = _string_list(params.get("all_cmdline_tokens"))
    if all_tokens and not all(_cmdline_contains(process.cmdline, token) for token in all_tokens):
        return False
    any_tokens = _string_list(params.get("any_cmdline_tokens"))
    if any_tokens and not any(_cmdline_contains(process.cmdline, token) for token in any_tokens):
        return False
    return True


def _cmdline_contains(cmdline: tuple[str, ...], token: str) -> bool:
    return any(token in part for part in cmdline)


def _executable_name(cmdline: tuple[str, ...]) -> str:
    if not cmdline:
        return ""
    return Path(cmdline[0]).name


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _int_param(params: dict[str, object], key: str) -> int | None:
    value = params.get(key)
    return int(value) if isinstance(value, int) else None


def _bool_param(params: dict[str, object], key: str) -> bool:
    return bool(params.get(key))
