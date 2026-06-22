"""Functional tests for session-tree ordering in ``build_tree``.

Pins the contract that every sibling level — root sessions, AI-to-AI children,
and project groups — ranks by its own ``created_at`` (newest first). A node's
position is its own creation time and nothing else; a newer descendant never
lifts its parent above a root created after it.
"""

from __future__ import annotations

import pytest

from teleclaude.api_models import ComputerDTO, ProjectDTO, SessionDTO
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    TreeNode,
    build_tree,
    is_computer_node,
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
    computer: str = _COMPUTER,
) -> SessionDTO:
    return SessionDTO(
        session_id=session_id,
        title=session_id,
        status="active",
        created_at=created_at,
        initiator_session_id=initiator,
        detached=detached,
        project_path=project_path,
        computer=computer,
    )


def _computer_info(name: str = _COMPUTER, *, is_local: bool = True) -> ComputerDisplayInfo:
    return ComputerDisplayInfo(
        computer=ComputerDTO(name=name, status="online", user=None, host=None, is_local=is_local),
        session_count=0,
        recent_activity=False,
    )


def _computer_names(tree: list[TreeNode]) -> list[str]:
    """Return computer-node names in top-to-bottom render order."""
    return [node.data.computer.name for node in tree if is_computer_node(node)]


def _project(path: str = _PROJECT, computer: str = _COMPUTER) -> ProjectDTO:
    return ProjectDTO(computer=computer, name="", path=path, description=None)


def _sorted_newest_first(sessions: list[SessionDTO]) -> list[SessionDTO]:
    """Mirror the caller's flat newest-first sort (``sessions.py``) before grouping.

    ``build_tree`` is always handed the session feed pre-sorted by ``created_at``
    descending; feeding the same here keeps the test faithful to the real input.
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


def test_parent_ranks_by_own_created_at_not_by_a_newer_child() -> None:
    # An orchestrator created earliest, holding a later non-detached worker, versus
    # a childless root created after the orchestrator. The parent ranks by its OWN
    # created_at, so the childless root sorts above it even though the orchestrator's
    # worker is the newest session overall. (Regression guard: subtree-max ranking.)
    orchestrator = _session("orch", "2026-06-18T02:14:00", detached=True)
    worker = _session("worker", "2026-06-18T02:26:00", initiator="orch")
    childless = _session("childless", "2026-06-18T02:18:00")

    tree = build_tree([_computer_info()], [_project()], _sorted_newest_first([orchestrator, worker, childless]))

    assert _flatten_session_ids(tree) == ["childless", "orch", "worker"]


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


def test_local_computer_renders_first_among_authoritative_computers() -> None:
    # Authoritative list arrives remote-first; the local machine name pins it first.
    computers = [
        _computer_info("Raspi", is_local=False),
        _computer_info("MozBook", is_local=True),
    ]
    tree = build_tree(computers, [], [], local_computer_name="MozBook")

    assert _computer_names(tree) == ["MozBook", "Raspi"]


def test_remotes_render_case_insensitive_alphabetical_after_local() -> None:
    computers = [
        _computer_info("zebra", is_local=False),
        _computer_info("Apple", is_local=False),
        _computer_info("MozBook", is_local=True),
        _computer_info("mango", is_local=False),
    ]
    tree = build_tree(computers, [], [], local_computer_name="MozBook")

    assert _computer_names(tree) == ["MozBook", "Apple", "mango", "zebra"]


def test_synthesized_computers_pin_local_first_over_newer_remote() -> None:
    # A newer remote session and an older local session, synthesized from the feed
    # (no authoritative computers). The feed is newest-first, so the remote would
    # land above local without the pin; the local name pins it first.
    local = _session("local-old", "2026-06-18T01:00:00", computer="MozBook")
    remote = _session("remote-new", "2026-06-18T05:00:00", computer="Raspi")

    tree = build_tree([], [], _sorted_newest_first([local, remote]), local_computer_name="MozBook")

    assert _computer_names(tree) == ["MozBook", "Raspi"]


def test_synthesized_local_via_local_sentinel_is_flagged_local() -> None:
    # A session whose computer is the "local" sentinel synthesizes a computer node
    # flagged is_local, even when the authoritative local name differs.
    session = _session("s1", "2026-06-18T01:00:00", computer="local")

    tree = build_tree([], [], [session], local_computer_name="MozBook")

    computer_nodes = [node for node in tree if is_computer_node(node)]
    assert len(computer_nodes) == 1
    assert computer_nodes[0].data.computer.name == _COMPUTER
    assert computer_nodes[0].data.computer.is_local is True
