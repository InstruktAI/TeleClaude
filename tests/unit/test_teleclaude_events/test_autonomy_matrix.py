"""Tests for AutonomyMatrix.resolve priority ordering."""

from __future__ import annotations

from teleclaude_events.domain_config import AutonomyLevel, AutonomyMatrix


def test_global_default_when_nothing_set() -> None:
    matrix = AutonomyMatrix(global_default=AutonomyLevel.notify)
    assert matrix.resolve("software", "my-cartridge", "task.created") == AutonomyLevel.notify


def test_domain_override_wins_over_global() -> None:
    matrix = AutonomyMatrix(
        global_default=AutonomyLevel.notify,
        by_domain={"software": AutonomyLevel.autonomous},
    )
    assert matrix.resolve("software", "my-cartridge", "task.created") == AutonomyLevel.autonomous


def test_cartridge_override_wins_over_domain() -> None:
    matrix = AutonomyMatrix(
        global_default=AutonomyLevel.notify,
        by_domain={"software": AutonomyLevel.autonomous},
        by_cartridge={"software/my-cartridge": AutonomyLevel.manual},
    )
    assert matrix.resolve("software", "my-cartridge", "task.created") == AutonomyLevel.manual


def test_event_type_wins_over_cartridge() -> None:
    matrix = AutonomyMatrix(
        global_default=AutonomyLevel.notify,
        by_domain={"software": AutonomyLevel.autonomous},
        by_cartridge={"software/my-cartridge": AutonomyLevel.manual},
        by_event_type={"software/task.created": AutonomyLevel.auto_notify},
    )
    assert matrix.resolve("software", "my-cartridge", "task.created") == AutonomyLevel.auto_notify


def test_priority_ordering_all_set() -> None:
    """event_type > cartridge > domain > global."""
    matrix = AutonomyMatrix(
        global_default=AutonomyLevel.manual,
        by_domain={"d": AutonomyLevel.notify},
        by_cartridge={"d/c": AutonomyLevel.auto_notify},
        by_event_type={"d/e": AutonomyLevel.autonomous},
    )
    assert matrix.resolve("d", "c", "e") == AutonomyLevel.autonomous
    # Remove event_type key — cartridge wins
    matrix2 = AutonomyMatrix(
        global_default=AutonomyLevel.manual,
        by_domain={"d": AutonomyLevel.notify},
        by_cartridge={"d/c": AutonomyLevel.auto_notify},
    )
    assert matrix2.resolve("d", "c", "e") == AutonomyLevel.auto_notify
    # Remove cartridge key — domain wins
    matrix3 = AutonomyMatrix(
        global_default=AutonomyLevel.manual,
        by_domain={"d": AutonomyLevel.notify},
    )
    assert matrix3.resolve("d", "c", "e") == AutonomyLevel.notify


def test_unknown_domain_falls_back_to_global() -> None:
    matrix = AutonomyMatrix(
        global_default=AutonomyLevel.autonomous,
        by_domain={"other": AutonomyLevel.manual},
    )
    assert matrix.resolve("unknown", "c", "e") == AutonomyLevel.autonomous


def test_cartridge_key_format() -> None:
    """Cartridge key must be '{domain}/{cartridge_id}'."""
    matrix = AutonomyMatrix(
        by_cartridge={"software/enrich-git": AutonomyLevel.autonomous},
    )
    assert matrix.resolve("software", "enrich-git", "task.created") == AutonomyLevel.autonomous
    assert matrix.resolve("software", "other", "task.created") == AutonomyLevel.notify
