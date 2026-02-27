"""Readiness projection derived from canonical integration events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, cast

from teleclaude.core.integration.events import (
    BranchPushedPayload,
    FinalizeReadyPayload,
    IntegrationBlockedPayload,
    IntegrationEvent,
    ReviewApprovedPayload,
)

ReadinessStatus = Literal["NOT_READY", "READY", "SUPERSEDED"]
ReachabilityChecker = Callable[[str, str, str], bool]
IntegratedChecker = Callable[[str, str], bool]


@dataclass(frozen=True, order=True)
class CandidateKey:
    """Canonical integration candidate identity."""

    slug: str
    branch: str
    sha: str


@dataclass(frozen=True)
class CandidateReadiness:
    """Current computed readiness for one integration candidate."""

    key: CandidateKey
    ready_at: str
    status: ReadinessStatus
    reasons: tuple[str, ...]
    superseded_by: CandidateKey | None


@dataclass(frozen=True)
class ProjectionUpdate:
    """State transition result after one event is applied."""

    transitioned_to_ready: tuple[CandidateReadiness, ...]
    transitioned_to_superseded: tuple[CandidateReadiness, ...]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class _CandidateFinalize:
    key: CandidateKey
    ready_at: datetime
    ready_at_raw: str

    def supersession_rank(self) -> tuple[datetime, str, str]:
        """Stable winner ordering for candidates within one slug."""
        return (self.ready_at, self.key.branch, self.key.sha)


class ReadinessProjection:
    """Compute integration readiness for `(slug, branch, sha)` candidates."""

    def __init__(
        self,
        *,
        reachability_checker: ReachabilityChecker,
        integrated_checker: IntegratedChecker,
        remote: str = "origin",
    ) -> None:
        self._remote = remote
        self._reachability_checker = reachability_checker
        self._integrated_checker = integrated_checker
        self.reset()

    def reset(self) -> None:
        """Clear all derived state."""
        self._review_approved_slugs: set[str] = set()
        self._finalize_by_key: dict[CandidateKey, _CandidateFinalize] = {}
        self._branch_pushes: set[tuple[str, str, str]] = set()
        self._readiness_by_key: dict[CandidateKey, CandidateReadiness] = {}

    def replay(self, events: tuple[IntegrationEvent, ...]) -> ProjectionUpdate:
        """Rebuild projection from persisted append-only events."""
        self.reset()
        last_update = ProjectionUpdate(transitioned_to_ready=(), transitioned_to_superseded=(), diagnostics=())
        for event in events:
            last_update = self.apply(event)
        return last_update

    def apply(self, event: IntegrationEvent) -> ProjectionUpdate:
        """Apply one canonical event and recompute readiness."""
        previous_status = {key: readiness.status for key, readiness in self._readiness_by_key.items()}
        if event.event_type == "review_approved":
            payload = cast(ReviewApprovedPayload, event.payload)
            self._apply_review_approved(payload)
        elif event.event_type == "finalize_ready":
            payload = cast(FinalizeReadyPayload, event.payload)
            self._apply_finalize_ready(payload)
        elif event.event_type == "branch_pushed":
            payload = cast(BranchPushedPayload, event.payload)
            self._apply_branch_pushed(payload)
        else:
            # integration_blocked is operational telemetry and does not alter readiness state.
            payload = cast(IntegrationBlockedPayload, event.payload)
            self._apply_integration_blocked(payload)

        self._recompute()

        transitioned_to_ready: list[CandidateReadiness] = []
        transitioned_to_superseded: list[CandidateReadiness] = []
        diagnostics: list[str] = []
        for key, readiness in self._readiness_by_key.items():
            previous = previous_status.get(key)
            if readiness.status == "READY" and previous != "READY":
                transitioned_to_ready.append(readiness)
            if readiness.status == "SUPERSEDED" and previous != "SUPERSEDED":
                transitioned_to_superseded.append(readiness)
                if readiness.superseded_by is not None:
                    diagnostics.append(
                        f"candidate {key.slug}/{key.branch}@{key.sha} superseded by "
                        f"{readiness.superseded_by.slug}/{readiness.superseded_by.branch}@{readiness.superseded_by.sha}"
                    )

        transitioned_to_ready.sort(key=lambda item: (item.key.slug, item.key.branch, item.key.sha))
        transitioned_to_superseded.sort(key=lambda item: (item.key.slug, item.key.branch, item.key.sha))
        return ProjectionUpdate(
            transitioned_to_ready=tuple(transitioned_to_ready),
            transitioned_to_superseded=tuple(transitioned_to_superseded),
            diagnostics=tuple(diagnostics),
        )

    def get_readiness(self, slug: str, branch: str, sha: str) -> CandidateReadiness | None:
        """Return readiness snapshot for one candidate."""
        return self._readiness_by_key.get(CandidateKey(slug=slug, branch=branch, sha=sha))

    def all_candidates(self) -> tuple[CandidateReadiness, ...]:
        """Return all candidate snapshots in stable order."""
        return tuple(
            self._readiness_by_key[key]
            for key in sorted(
                self._readiness_by_key,
                key=lambda item: (
                    item.slug,
                    self._finalize_by_key[item].ready_at,
                    item.branch,
                    item.sha,
                ),
            )
        )

    def _apply_review_approved(self, payload: ReviewApprovedPayload) -> None:
        self._review_approved_slugs.add(payload["slug"])

    def _apply_finalize_ready(self, payload: FinalizeReadyPayload) -> None:
        key = CandidateKey(slug=payload["slug"], branch=payload["branch"], sha=payload["sha"])
        self._finalize_by_key[key] = _CandidateFinalize(
            key=key,
            ready_at=datetime.fromisoformat(payload["ready_at"]),
            ready_at_raw=payload["ready_at"],
        )

    def _apply_branch_pushed(self, payload: BranchPushedPayload) -> None:
        self._branch_pushes.add((payload["branch"], payload["sha"], payload["remote"]))

    def _apply_integration_blocked(self, _payload: IntegrationBlockedPayload) -> None:
        return

    def _recompute(self) -> None:
        latest_by_slug: dict[str, _CandidateFinalize] = {}
        for candidate in self._finalize_by_key.values():
            current = latest_by_slug.get(candidate.key.slug)
            if current is None or candidate.supersession_rank() > current.supersession_rank():
                latest_by_slug[candidate.key.slug] = candidate

        next_readiness: dict[CandidateKey, CandidateReadiness] = {}
        for key, finalize in self._finalize_by_key.items():
            latest = latest_by_slug.get(key.slug)
            superseded_by: CandidateKey | None = None
            if latest is not None and latest.key != key and latest.supersession_rank() >= finalize.supersession_rank():
                superseded_by = latest.key

            if superseded_by is not None:
                readiness = CandidateReadiness(
                    key=key,
                    ready_at=finalize.ready_at_raw,
                    status="SUPERSEDED",
                    reasons=("newer finalize_ready exists for slug",),
                    superseded_by=superseded_by,
                )
                next_readiness[key] = readiness
                continue

            reasons: list[str] = []
            if key.slug not in self._review_approved_slugs:
                reasons.append("missing review_approved for slug")

            branch_pushed = (key.branch, key.sha, self._remote) in self._branch_pushes
            if not branch_pushed:
                reasons.append(f"missing branch_pushed for {self._remote}/{key.branch}@{key.sha}")

            if branch_pushed and not self._reachability_checker(key.branch, key.sha, self._remote):
                reasons.append(f"sha {key.sha} is not reachable from {self._remote}/{key.branch}")

            if self._integrated_checker(key.sha, f"{self._remote}/main"):
                reasons.append(f"sha {key.sha} already reachable from {self._remote}/main")

            status: ReadinessStatus = "READY" if not reasons else "NOT_READY"
            next_readiness[key] = CandidateReadiness(
                key=key,
                ready_at=finalize.ready_at_raw,
                status=status,
                reasons=tuple(reasons),
                superseded_by=None,
            )

        self._readiness_by_key = next_readiness
