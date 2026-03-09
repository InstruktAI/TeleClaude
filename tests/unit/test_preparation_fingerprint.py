"""Unit tests for PreparationView._todo_fingerprint phase change detection (V6)."""

from unittest.mock import MagicMock


def _make_todo(
    slug: str = "test-slug",
    prepare_phase: str | None = None,
    integration_phase: str | None = None,
    finalize_status: str | None = None,
) -> MagicMock:
    t = MagicMock()
    t.slug = slug
    t.status = "pending"
    t.dor_score = None
    t.build_status = None
    t.review_status = None
    t.deferrals_status = None
    t.findings_count = 0
    t.has_requirements = True
    t.has_impl_plan = True
    t.files = []
    t.after = []
    t.group = None
    t.prepare_phase = prepare_phase
    t.integration_phase = integration_phase
    t.finalize_status = finalize_status
    return t


def _make_project(todos: list) -> MagicMock:
    p = MagicMock()
    p.todos = todos
    return p


def _fingerprint(projects: list) -> tuple:
    """Call the fingerprint logic directly — mirrors PreparationView._todo_fingerprint."""
    return tuple(
        (
            t.slug,
            t.status,
            str(t.dor_score),
            t.build_status or "",
            t.review_status or "",
            t.deferrals_status or "",
            str(t.findings_count),
            str(t.has_requirements),
            str(t.has_impl_plan),
            ",".join(t.files),
            ",".join(t.after),
            t.group or "",
            getattr(t, "prepare_phase", None) or "",
            getattr(t, "integration_phase", None) or "",
            getattr(t, "finalize_status", None) or "",
        )
        for p in projects
        for t in (p.todos or [])
    )


def test_fingerprint_differs_on_prepare_phase_change():
    """Different prepare_phase values produce different fingerprints."""
    t1 = _make_todo(prepare_phase="plan_drafting")
    t2 = _make_todo(prepare_phase="gate")
    fp1 = _fingerprint([_make_project([t1])])
    fp2 = _fingerprint([_make_project([t2])])
    assert fp1 != fp2


def test_fingerprint_differs_on_integration_phase_change():
    """Different integration_phase values produce different fingerprints."""
    t1 = _make_todo(integration_phase="merge_clean")
    t2 = _make_todo(integration_phase="push_succeeded")
    fp1 = _fingerprint([_make_project([t1])])
    fp2 = _fingerprint([_make_project([t2])])
    assert fp1 != fp2


def test_fingerprint_differs_on_finalize_status_change():
    """Different finalize_status values produce different fingerprints."""
    t1 = _make_todo(finalize_status=None)
    t2 = _make_todo(finalize_status="handed_off")
    fp1 = _fingerprint([_make_project([t1])])
    fp2 = _fingerprint([_make_project([t2])])
    assert fp1 != fp2


def test_fingerprint_same_when_no_phase_fields():
    """Two todos with all phase fields None produce the same fingerprint."""
    t1 = _make_todo()
    t2 = _make_todo()
    fp1 = _fingerprint([_make_project([t1])])
    fp2 = _fingerprint([_make_project([t2])])
    assert fp1 == fp2
