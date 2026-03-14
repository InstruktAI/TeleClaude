"""Characterization tests for teleclaude.core.integration.readiness_projection."""

from __future__ import annotations

from teleclaude.core.integration.events import build_integration_event
from teleclaude.core.integration.readiness_projection import (
    CandidateKey,
    ReadinessProjection,
)

_READY_AT = "2024-01-01T12:00:00+00:00"
_APPROVED_AT = "2024-01-01T11:00:00+00:00"
_PUSHED_AT = "2024-01-01T11:30:00+00:00"


def _make_projection(*, reachable: bool = True, integrated: bool = False) -> ReadinessProjection:
    return ReadinessProjection(
        reachability_checker=lambda _b, _s, _r: reachable,
        integrated_checker=lambda _s, _ref: integrated,
        remote="origin",
    )


def _build_review_approved(slug: str) -> object:
    return build_integration_event(
        "review_approved",
        {"slug": slug, "approved_at": _APPROVED_AT, "review_round": 1, "reviewer_session_id": "rev-1"},
    )


def _build_finalize_ready(slug: str, branch: str, sha: str) -> object:
    return build_integration_event(
        "finalize_ready",
        {
            "slug": slug,
            "branch": branch,
            "sha": sha,
            "worker_session_id": "worker-1",
            "orchestrator_session_id": "orch-1",
            "ready_at": _READY_AT,
        },
    )


def _build_branch_pushed(branch: str, sha: str) -> object:
    return build_integration_event(
        "branch_pushed",
        {"branch": branch, "sha": sha, "remote": "origin", "pushed_at": _PUSHED_AT, "pusher": "agent-1"},
    )


# ---------------------------------------------------------------------------
# CandidateKey
# ---------------------------------------------------------------------------


def test_candidate_key_is_orderable() -> None:
    k1 = CandidateKey(slug="a", branch="b", sha="c")
    k2 = CandidateKey(slug="b", branch="b", sha="c")
    assert k1 < k2


def test_candidate_key_equality() -> None:
    k1 = CandidateKey(slug="a", branch="b", sha="c")
    k2 = CandidateKey(slug="a", branch="b", sha="c")
    assert k1 == k2


# ---------------------------------------------------------------------------
# ReadinessProjection.apply
# ---------------------------------------------------------------------------


def test_projection_new_candidate_not_ready_without_all_events() -> None:
    proj = _make_projection()
    event = _build_finalize_ready("slug-a", "branch-a", "sha-a")
    update = proj.apply(event)
    # No review_approved or branch_pushed yet → not READY
    assert len(update.transitioned_to_ready) == 0
    readiness = proj.get_readiness("slug-a", "branch-a", "sha-a")
    assert readiness is not None
    assert readiness.status == "NOT_READY"


def test_projection_candidate_becomes_ready_after_all_events() -> None:
    proj = _make_projection(reachable=True, integrated=False)
    proj.apply(_build_review_approved("slug-a"))
    proj.apply(_build_branch_pushed("branch-a", "sha-a"))
    update = proj.apply(_build_finalize_ready("slug-a", "branch-a", "sha-a"))
    assert len(update.transitioned_to_ready) == 1
    assert update.transitioned_to_ready[0].status == "READY"


def test_projection_candidate_not_ready_when_already_integrated() -> None:
    proj = _make_projection(reachable=True, integrated=True)
    proj.apply(_build_review_approved("slug-a"))
    proj.apply(_build_branch_pushed("branch-a", "sha-a"))
    proj.apply(_build_finalize_ready("slug-a", "branch-a", "sha-a"))
    readiness = proj.get_readiness("slug-a", "branch-a", "sha-a")
    assert readiness is not None
    assert readiness.status == "NOT_READY"


def test_projection_older_candidate_superseded_by_newer() -> None:
    proj = _make_projection()
    # First finalize_ready for slug-a at a given time
    proj.apply(
        build_integration_event(
            "finalize_ready",
            {
                "slug": "slug-a",
                "branch": "branch-old",
                "sha": "sha-old",
                "worker_session_id": "w1",
                "orchestrator_session_id": "o1",
                "ready_at": "2024-01-01T10:00:00+00:00",
            },
        )
    )
    # Newer finalize_ready for same slug
    proj.apply(
        build_integration_event(
            "finalize_ready",
            {
                "slug": "slug-a",
                "branch": "branch-new",
                "sha": "sha-new",
                "worker_session_id": "w1",
                "orchestrator_session_id": "o1",
                "ready_at": "2024-01-02T10:00:00+00:00",
            },
        )
    )
    old_readiness = proj.get_readiness("slug-a", "branch-old", "sha-old")
    assert old_readiness is not None
    assert old_readiness.status == "SUPERSEDED"
    assert old_readiness.superseded_by is not None


# ---------------------------------------------------------------------------
# ReadinessProjection.replay
# ---------------------------------------------------------------------------


def test_projection_replay_rebuilds_from_events() -> None:
    proj = _make_projection(reachable=True, integrated=False)
    events = (
        _build_review_approved("slug-b"),
        _build_branch_pushed("branch-b", "sha-b"),
        _build_finalize_ready("slug-b", "branch-b", "sha-b"),
    )
    proj.replay(events)
    readiness = proj.get_readiness("slug-b", "branch-b", "sha-b")
    assert readiness is not None
    assert readiness.status == "READY"


def test_projection_reset_clears_all_state() -> None:
    proj = _make_projection(reachable=True, integrated=False)
    proj.apply(_build_review_approved("slug-c"))
    proj.apply(_build_finalize_ready("slug-c", "branch-c", "sha-c"))
    proj.reset()
    assert proj.get_readiness("slug-c", "branch-c", "sha-c") is None
    assert len(proj.all_candidates()) == 0


# ---------------------------------------------------------------------------
# ReadinessProjection.all_candidates
# ---------------------------------------------------------------------------


def test_projection_all_candidates_stable_order() -> None:
    proj = _make_projection()
    proj.apply(_build_finalize_ready("slug-z", "bz", "sz"))
    proj.apply(_build_finalize_ready("slug-a", "ba", "sa"))
    candidates = proj.all_candidates()
    assert len(candidates) == 2
    slugs = [c.key.slug for c in candidates]
    assert slugs == sorted(slugs)
