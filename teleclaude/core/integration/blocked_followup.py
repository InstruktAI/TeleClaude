"""Durable follow-up linkage for blocked integration candidates."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast

from teleclaude.core.integration.events import IntegrationBlockedPayload
from teleclaude.core.integration.readiness_projection import CandidateKey

FollowUpStatus = Literal["open", "resolved"]


class BlockedFollowUpError(RuntimeError):
    """Raised when follow-up linkage state cannot be loaded or persisted."""


@dataclass(frozen=True)
class BlockedFollowUpLink:
    """Durable mapping between one blocked candidate and one follow-up todo."""

    key: CandidateKey
    follow_up_slug: str
    status: FollowUpStatus
    created_at: str
    last_blocked_at: str
    resolved_at: str | None
    last_conflict_evidence: tuple[str, ...]
    last_diagnostics: tuple[str, ...]
    next_action: str


class _FollowUpRecordPayload(TypedDict):
    slug: str
    branch: str
    sha: str
    follow_up_slug: str
    status: FollowUpStatus
    created_at: str
    last_blocked_at: str
    resolved_at: str | None
    last_conflict_evidence: list[str]
    last_diagnostics: list[str]
    next_action: str


class _FollowUpStatePayload(TypedDict):
    version: int
    links: list[_FollowUpRecordPayload]


class BlockedFollowUpStore:
    """File-backed store for blocked-candidate follow-up todo linkage."""

    def __init__(self, *, state_path: Path, todos_root: Path) -> None:
        self._state_path = state_path
        self._todos_root = todos_root
        self._links_by_key: dict[CandidateKey, BlockedFollowUpLink] = {}
        self._keys_by_follow_up_slug: dict[str, CandidateKey] = {}
        self._load_state()

    def ensure_follow_up(self, payload: IntegrationBlockedPayload) -> BlockedFollowUpLink:
        """Create or update a follow-up link for one blocked candidate."""
        key = CandidateKey(slug=payload["slug"], branch=payload["branch"], sha=payload["sha"])
        blocked_at = _normalize_iso8601(payload["blocked_at"])
        evidence = tuple(payload["conflict_evidence"])
        diagnostics = tuple(payload["diagnostics"])
        next_action = payload["next_action"]

        existing = self._links_by_key.get(key)
        if existing is not None:
            updated = BlockedFollowUpLink(
                key=existing.key,
                follow_up_slug=existing.follow_up_slug,
                status=existing.status,
                created_at=existing.created_at,
                last_blocked_at=blocked_at,
                resolved_at=existing.resolved_at,
                last_conflict_evidence=evidence,
                last_diagnostics=diagnostics,
                next_action=next_action,
            )
            self._links_by_key[key] = updated
            self._keys_by_follow_up_slug[updated.follow_up_slug] = key
            self._ensure_follow_up_todo(updated)
            self._persist_state()
            return updated

        preferred_slug = payload.get("follow_up_slug", "").strip()
        follow_up_slug = (
            _normalize_slug(preferred_slug) if preferred_slug else self._allocate_follow_up_slug(candidate_key=key)
        )
        if not follow_up_slug:
            follow_up_slug = self._allocate_follow_up_slug(candidate_key=key)

        created_at = _format_timestamp(datetime.now(tz=UTC))
        link = BlockedFollowUpLink(
            key=key,
            follow_up_slug=follow_up_slug,
            status="open",
            created_at=created_at,
            last_blocked_at=blocked_at,
            resolved_at=None,
            last_conflict_evidence=evidence,
            last_diagnostics=diagnostics,
            next_action=next_action,
        )
        self._links_by_key[key] = link
        self._keys_by_follow_up_slug[follow_up_slug] = key
        self._ensure_follow_up_todo(link)
        self._persist_state()
        return link

    def mark_resolved(self, *, follow_up_slug: str, resolved_at: str | None = None) -> BlockedFollowUpLink:
        """Mark a follow-up as resolved so it can be resumed safely."""
        normalized_slug = _normalize_slug(follow_up_slug)
        key = self._keys_by_follow_up_slug.get(normalized_slug)
        if key is None:
            raise BlockedFollowUpError(f"unknown follow-up slug: {follow_up_slug}")

        existing = self._links_by_key[key]
        normalized_resolved_at = (
            _normalize_iso8601(resolved_at) if resolved_at is not None else _format_timestamp(datetime.now(tz=UTC))
        )
        updated = BlockedFollowUpLink(
            key=existing.key,
            follow_up_slug=existing.follow_up_slug,
            status="resolved",
            created_at=existing.created_at,
            last_blocked_at=existing.last_blocked_at,
            resolved_at=normalized_resolved_at,
            last_conflict_evidence=existing.last_conflict_evidence,
            last_diagnostics=existing.last_diagnostics,
            next_action=existing.next_action,
        )
        self._links_by_key[key] = updated
        self._keys_by_follow_up_slug[updated.follow_up_slug] = key
        self._persist_state()
        return updated

    def candidate_for_follow_up(self, *, follow_up_slug: str) -> CandidateKey | None:
        """Return candidate key linked to one follow-up slug."""
        return self._keys_by_follow_up_slug.get(_normalize_slug(follow_up_slug))

    def get_by_candidate(self, *, key: CandidateKey) -> BlockedFollowUpLink | None:
        """Return follow-up link for one candidate key."""
        return self._links_by_key.get(key)

    def links(self) -> tuple[BlockedFollowUpLink, ...]:
        """Return all links sorted by candidate identity."""
        return tuple(
            self._links_by_key[key]
            for key in sorted(self._links_by_key, key=lambda item: (item.slug, item.branch, item.sha))
        )

    def _allocate_follow_up_slug(self, *, candidate_key: CandidateKey) -> str:
        normalized_slug = _normalize_slug(candidate_key.slug)
        if not normalized_slug:
            normalized_slug = "todo"
        base = (
            _normalize_slug(f"{normalized_slug}-integration-blocked-{candidate_key.sha[:7]}") or "integration-blocked"
        )

        attempt = base
        suffix = 2
        while attempt in self._keys_by_follow_up_slug:
            owner = self._keys_by_follow_up_slug[attempt]
            if owner == candidate_key:
                return attempt
            attempt = f"{base}-{suffix}"
            suffix += 1
        return attempt

    def _ensure_follow_up_todo(self, link: BlockedFollowUpLink) -> None:
        todo_dir = self._todos_root / link.follow_up_slug
        todo_dir.mkdir(parents=True, exist_ok=True)

        requirements_path = todo_dir / "requirements.md"
        if not requirements_path.exists():
            requirements_path.write_text(
                _render_requirements(link),
                encoding="utf-8",
            )

        plan_path = todo_dir / "implementation-plan.md"
        if not plan_path.exists():
            plan_path.write_text(
                _render_implementation_plan(link),
                encoding="utf-8",
            )

        state_path = todo_dir / "state.yaml"
        if not state_path.exists():
            state_path.write_text("build: pending\nreview: pending\n", encoding="utf-8")

    def _load_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._state_path.exists():
            return

        raw_text = self._state_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise BlockedFollowUpError(f"invalid blocked follow-up state JSON: {self._state_path}") from exc
        if not isinstance(payload, dict):
            raise BlockedFollowUpError("blocked follow-up state payload must be an object")

        raw_links = payload.get("links", [])
        if not isinstance(raw_links, list):
            raise BlockedFollowUpError("blocked follow-up state field 'links' must be a list")

        self._links_by_key.clear()
        self._keys_by_follow_up_slug.clear()
        for raw_link in raw_links:
            if not isinstance(raw_link, dict):
                raise BlockedFollowUpError("blocked follow-up record must be an object")
            link = _link_from_payload(raw_link)
            if link.key in self._links_by_key:
                raise BlockedFollowUpError(
                    f"duplicate blocked follow-up link for {link.key.slug}/{link.key.branch}@{link.key.sha}"
                )
            if link.follow_up_slug in self._keys_by_follow_up_slug:
                raise BlockedFollowUpError(f"duplicate follow-up slug mapping: {link.follow_up_slug}")
            self._links_by_key[link.key] = link
            self._keys_by_follow_up_slug[link.follow_up_slug] = link.key

    def _persist_state(self) -> None:
        payload: _FollowUpStatePayload = {
            "version": 1,
            "links": [_link_to_payload(link) for link in self.links()],
        }
        serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        temp_path = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")

        with temp_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write(serialized)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temp_path, self._state_path)


def _link_from_payload(payload: dict[object, object]) -> BlockedFollowUpLink:
    key = CandidateKey(
        slug=_required_str(payload, "slug"),
        branch=_required_str(payload, "branch"),
        sha=_required_str(payload, "sha"),
    )
    follow_up_slug = _normalize_slug(_required_str(payload, "follow_up_slug"))
    if not follow_up_slug:
        raise BlockedFollowUpError("follow_up_slug must contain at least one valid slug token")

    status = _status_from_value(payload.get("status"))
    created_at = _normalize_iso8601(_required_str(payload, "created_at"))
    last_blocked_at = _normalize_iso8601(_required_str(payload, "last_blocked_at"))
    resolved_at = _optional_iso8601(payload.get("resolved_at"), field_name="resolved_at")
    evidence = tuple(
        _required_non_empty_str_list(payload.get("last_conflict_evidence"), field_name="last_conflict_evidence")
    )
    diagnostics = tuple(_required_non_empty_str_list(payload.get("last_diagnostics"), field_name="last_diagnostics"))
    next_action = _required_str(payload, "next_action").strip()
    if not next_action:
        raise BlockedFollowUpError("next_action must be a non-empty string")

    return BlockedFollowUpLink(
        key=key,
        follow_up_slug=follow_up_slug,
        status=status,
        created_at=created_at,
        last_blocked_at=last_blocked_at,
        resolved_at=resolved_at,
        last_conflict_evidence=evidence,
        last_diagnostics=diagnostics,
        next_action=next_action,
    )


def _link_to_payload(link: BlockedFollowUpLink) -> _FollowUpRecordPayload:
    return {
        "slug": link.key.slug,
        "branch": link.key.branch,
        "sha": link.key.sha,
        "follow_up_slug": link.follow_up_slug,
        "status": link.status,
        "created_at": link.created_at,
        "last_blocked_at": link.last_blocked_at,
        "resolved_at": link.resolved_at,
        "last_conflict_evidence": list(link.last_conflict_evidence),
        "last_diagnostics": list(link.last_diagnostics),
        "next_action": link.next_action,
    }


def _required_str(payload: dict[object, object], field_name: str) -> str:
    raw = payload.get(field_name)
    if not isinstance(raw, str):
        raise BlockedFollowUpError(f"{field_name} must be a string")
    value = raw.strip()
    if not value:
        raise BlockedFollowUpError(f"{field_name} must be a non-empty string")
    return value


def _required_non_empty_str_list(raw: object, *, field_name: str) -> list[str]:
    if not isinstance(raw, list):
        raise BlockedFollowUpError(f"{field_name} must be a non-empty list of strings")
    normalized: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise BlockedFollowUpError(f"{field_name} must contain only non-empty strings")
        normalized.append(item.strip())
    if not normalized:
        raise BlockedFollowUpError(f"{field_name} must be a non-empty list of strings")
    return normalized


def _optional_iso8601(raw: object, *, field_name: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise BlockedFollowUpError(f"{field_name} must be a string when present")
    return _normalize_iso8601(raw)


def _status_from_value(raw: object) -> FollowUpStatus:
    if raw not in {"open", "resolved"}:
        raise BlockedFollowUpError(f"status must be one of ['open', 'resolved'], got {raw!r}")
    return cast(FollowUpStatus, raw)


def _normalize_slug(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        return ""
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def _normalize_iso8601(raw_value: str) -> str:
    adjusted = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(adjusted)
    except ValueError as exc:
        raise BlockedFollowUpError(f"invalid ISO8601 timestamp: {raw_value!r}") from exc
    if parsed.tzinfo is None:
        raise BlockedFollowUpError(f"timestamp must include timezone offset: {raw_value!r}")
    return _format_timestamp(parsed)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _render_requirements(link: BlockedFollowUpLink) -> str:
    return (
        f"# Requirements: {link.follow_up_slug}\n\n"
        "## Goal\n\n"
        "Resolve integration blockers and restore candidate readiness.\n\n"
        "## Source Candidate\n\n"
        f"- slug: `{link.key.slug}`\n"
        f"- branch: `{link.key.branch}`\n"
        f"- sha: `{link.key.sha}`\n"
        f"- blocked_at: `{link.last_blocked_at}`\n\n"
        "## Blocking Evidence\n\n"
        + "\n".join(f"- {item}" for item in link.last_conflict_evidence)
        + "\n\n## Diagnostics\n\n"
        + "\n".join(f"- {item}" for item in link.last_diagnostics)
        + "\n\n## Next Action\n\n"
        + f"{link.next_action}\n"
    )


def _render_implementation_plan(link: BlockedFollowUpLink) -> str:
    return (
        f"# Implementation Plan: {link.follow_up_slug}\n\n"
        "## Remediation Tasks\n\n"
        "- [ ] Resolve blocking evidence for source candidate.\n"
        "- [ ] Push remediated branch/sha and confirm readiness predicates.\n"
        "- [ ] Trigger integrator resume path for linked candidate.\n"
        f"- [ ] Verify candidate `{link.key.slug}/{link.key.branch}@{link.key.sha}` re-enters queue.\n"
    )
