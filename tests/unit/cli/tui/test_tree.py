from __future__ import annotations

import pytest

from teleclaude.api_models import ComputerDTO, ProjectDTO, SessionDTO
from teleclaude.cli.tui.tree import (
    ComputerDisplayInfo,
    build_tree,
    is_computer_node,
    is_project_node,
    is_session_node,
)


@pytest.mark.unit
def test_build_tree_adds_offline_computer_and_placeholder_project_for_orphan_sessions() -> None:
    computers = [
        ComputerDisplayInfo(
            ComputerDTO(name="c1", status="online", user="alice", host="host", is_local=True),
            session_count=0,
            recent_activity=False,
        )
    ]
    projects = [ProjectDTO(computer="c1", name="proj", path="/repo", description=None)]
    sessions = [SessionDTO(session_id="s3", title="orphan", status="idle", project_path="/missing", computer="c2")]

    roots = build_tree(computers, projects, sessions)
    orphan_computer = roots[1]
    assert is_computer_node(orphan_computer)
    placeholder_project = orphan_computer.children[0]
    assert is_project_node(placeholder_project)

    assert orphan_computer.data.computer.name == "c2"
    assert orphan_computer.data.computer.status == "offline"
    assert orphan_computer.data.computer.is_local is False
    assert placeholder_project.data.name == ""
    assert placeholder_project.data.path == "/missing"


@pytest.mark.unit
def test_build_tree_nests_initiated_sessions_under_their_parent_session() -> None:
    computers = [
        ComputerDisplayInfo(
            ComputerDTO(name="c1", status="online", user="alice", host="host", is_local=True),
            session_count=0,
            recent_activity=False,
        )
    ]
    projects = [ProjectDTO(computer="c1", name="proj", path="/repo", description=None)]
    sessions = [
        SessionDTO(session_id="s1", title="root", status="idle", project_path="/repo", computer="c1"),
        SessionDTO(
            session_id="s2",
            title="child",
            status="idle",
            project_path="/repo/trees/w1",
            computer="c1",
            initiator_session_id="s1",
        ),
    ]

    roots = build_tree(computers, projects, sessions)
    root_session = roots[0].children[0].children[0]
    assert is_session_node(root_session)
    child_session = root_session.children[0]
    assert is_session_node(child_session)

    assert root_session.data.session.session_id == "s1"
    assert child_session.data.session.session_id == "s2"
    assert child_session.data.display_index == "1.1"
    assert child_session.parent is root_session
