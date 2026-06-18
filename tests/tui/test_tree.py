"""Functional tests for session-tree ordering in ``build_tree``.

Pins the contract that the branch containing the newest ``created_at`` surfaces
first at every level — sessions, AI-to-AI children, and projects — so the latest
session is always visible at the top, even when it is nested beneath an older
orchestrator (the buried-newest regression).
"""

from __future__ import annotations

import pytest

from teleclaude.api_models import ComputerDTO, ProjectDTO, SessionDTO
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    TreeNode,
    build_tree,
    is_session_node,
)

pytestmark = pytest.mark.functional

_COMPUTER = "local"
_PROJECT = "/repo"


def _session(
    session_id: str,
    created_at: str,
    *,
    initiator: str | None = None,
    detached: bool = False,
    project_path: str = _PROJECT,
) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="active",
        created_at=created_at,
        initiator_session_id=initiator,
        detached=detached,
        project_path=project_path,
        computer=_COMPUTER,
    )


def _computer_info(name: str = _COMPUTER) -> ComputerDisplayInfo:
    return ComputerDisplayInfo(
        computer=ComputerDTO(name=name, status="online", user=None, host=None, is_local=True),
        session_count=0,
        recent_activity=False,
    )


def _project(path: str = _PROJECT, computer: str = _COMPUTER) -> ProjectDTO:
    return ProjectDTO(computer=computer, name="", path=path, description=None)


def _sorted_newest_first(sessions: list[SessionDTO]) -> list[SessionDTO]:
    """Mirror the caller's flat newest-first sort (``sessions.py``) before grouping.

    ``build_tree`` is always handed the session feed pre-sorted by ``created_at``
    descending; feeding the same here keeps the test faithful to the real input
    and proves the fix removes the cause rather than leaning on that pre-sort.
    """
    return sorted(sessions, key=lambda s: s.created_at or "", reverse=True)


def _flatten_session_ids(tree: list[TreeNode]) -> list[str]:
    """Return session ids in top-to-bottom render order."""
    ids: list[str] = []

    def walk(node: TreeNode) -> None:
        if is_session_node(node):
            ids.append(node.data.session.session_id)
        for child in node.children:
            walk(child)

    for node in tree:
        walk(node)
    return ids


def test_newer_child_lifts_its_parent_branch_above_a_newer_childless_root() -> None:
    # Orchestrator created earliest with a later non-detached child worker, versus
    # a more-recently-created childless orchestrator. The child must lift its
    # parent's branch above the newer childless root (buried-newest regression).
    orchestrator = _session("orch", "2026-06-18T02:14:00", detached=True)
    worker = _session("worker", "2026-06-18T02:26:00", initiator="orch")
    childless = _session("childless", "2026-06-18T02:18:00")

    tree = build_tree([_computer_info()], [_project()], _sorted_newest_first([orchestrator, worker, childless]))

    assert _flatten_session_ids(tree) == ["orch", "worker", "childless"]


def test_children_render_newest_first_within_a_parent() -> None:
    parent = _session("parent", "2026-06-18T02:00:00", detached=True)
    older_child = _session("child-old", "2026-06-18T02:05:00", initiator="parent")
    newer_child = _session("child-new", "2026-06-18T02:30:00", initiator="parent")

    tree = build_tree([_computer_info()], [_project()], _sorted_newest_first([parent, older_child, newer_child]))

    assert _flatten_session_ids(tree) == ["parent", "child-new", "child-old"]


def test_root_sessions_without_children_render_newest_first() -> None:
    older = _session("older", "2026-06-18T01:00:00")
    newest = _session("newest", "2026-06-18T05:00:00")
    middle = _session("middle", "2026-06-18T03:00:00")

    tree = build_tree([_computer_info()], [_project()], _sorted_newest_first([older, newest, middle]))

    assert _flatten_session_ids(tree) == ["newest", "middle", "older"]


def test_project_with_newest_session_surfaces_first() -> None:
    project_a = "/repo-a"
    project_b = "/repo-b"
    in_a = _session("in-a", "2026-06-18T02:00:00", project_path=project_a)
    in_b = _session("in-b", "2026-06-18T04:00:00", project_path=project_b)

    tree = build_tree(
        [_computer_info()],
        [_project(project_a), _project(project_b)],
        _sorted_newest_first([in_a, in_b]),
    )

    # Project B holds the newest session, so its session renders before A's.
    assert _flatten_session_ids(tree) == ["in-b", "in-a"]
