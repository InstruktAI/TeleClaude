"""Unit tests for TUI tree building."""

# type: ignore - test fixtures use concrete types that are compatible

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.tree import ComputerDisplayInfo, build_tree


def make_computer(name: str = "local", host: str = "localhost") -> ComputerDisplayInfo:
    info = ComputerInfo(
        name=name,
        status="online",
        user=None,
        host=host,
        is_local=name == "local",
        tmux_binary=None,
    )
    return ComputerDisplayInfo(computer=info, session_count=0, recent_activity=False)


def make_project(computer: str = "local", path: str = "/home/user/project") -> ProjectInfo:
    return ProjectInfo(computer=computer, name="", path=path, description=None)


def make_session(
    session_id: str,
    *,
    computer: str = "local",
    project_path: str = "/home/user/project",
    title: str = "Main Session",
    initiator_session_id: str | None = None,
) -> SessionInfo:
    return SessionInfo(
        session_id=session_id,
        origin_adapter="telegram",
        title=title,
        project_path=project_path,
        thinking_mode="slow",
        active_agent=None,
        status="active",
        created_at=None,
        last_activity=None,
        last_input=None,
        last_input_at=None,
        last_output=None,
        last_output_at=None,
        tmux_session_name=None,
        initiator_session_id=initiator_session_id,
        computer=computer,
    )


def test_build_tree_empty_inputs():
    """Test build_tree with no data."""
    tree = build_tree([], [], [])
    assert tree == []


def test_build_tree_single_computer_no_projects():
    """Test build_tree with computer but no projects."""
    computers = [make_computer()]
    tree = build_tree(computers, [], [])

    assert len(tree) == 1
    assert tree[0].type == "computer"
    assert tree[0].data.computer.name == "local"
    assert tree[0].depth == 0
    assert len(tree[0].children) == 0


def test_build_tree_computer_with_project_no_sessions():
    """Test build_tree with computer and project but no sessions."""
    computers = [make_computer()]
    projects = [make_project()]
    tree = build_tree(computers, projects, [])

    assert len(tree) == 1
    assert tree[0].type == "computer"
    assert len(tree[0].children) == 1

    project_node = tree[0].children[0]
    assert project_node.type == "project"
    assert project_node.data.path == "/home/user/project"
    assert project_node.depth == 1
    assert len(project_node.children) == 0


def test_build_tree_with_top_level_session():
    """Test build_tree with a top-level session (no initiator)."""
    computers = [make_computer()]
    projects = [make_project()]
    sessions = [
        make_session("sess-1"),
    ]
    tree = build_tree(computers, projects, sessions)

    project_node = tree[0].children[0]
    assert len(project_node.children) == 1

    session_node = project_node.children[0]
    assert session_node.type == "session"
    assert session_node.data.session.session_id == "sess-1"
    assert session_node.data.session.title == "Main Session"
    assert session_node.depth == 2


def test_build_tree_with_ai_to_ai_nesting():
    """Test build_tree with AI-to-AI session nesting (initiator-worker)."""
    computers = [make_computer()]
    projects = [make_project()]
    sessions = [
        make_session("sess-parent", title="Parent Session"),
        make_session("sess-child", title="Child Session", initiator_session_id="sess-parent"),
    ]
    tree = build_tree(computers, projects, sessions)

    project_node = tree[0].children[0]
    assert len(project_node.children) == 1

    parent_session = project_node.children[0]
    assert parent_session.data.session.session_id == "sess-parent"
    assert len(parent_session.children) == 1

    child_session = parent_session.children[0]
    assert child_session.data.session.session_id == "sess-child"
    assert child_session.data.session.initiator_session_id == "sess-parent"
    assert child_session.depth == 3


def test_build_tree_with_deep_nesting():
    """Test build_tree with multiple levels of AI-to-AI nesting."""
    computers = [make_computer()]
    projects = [make_project()]
    sessions = [
        make_session("sess-1", title="Level 1"),
        make_session("sess-2", title="Level 2", initiator_session_id="sess-1"),
        make_session("sess-3", title="Level 3", initiator_session_id="sess-2"),
    ]
    tree = build_tree(computers, projects, sessions)

    project_node = tree[0].children[0]
    sess1 = project_node.children[0]
    sess2 = sess1.children[0]
    sess3 = sess2.children[0]

    assert sess1.depth == 2
    assert sess2.depth == 3
    assert sess3.depth == 4
    assert sess3.data.session.session_id == "sess-3"


def test_build_tree_multiple_computers():
    """Test build_tree with multiple computers."""
    computers = [
        make_computer(),
        make_computer(name="remote", host="192.168.1.10"),
    ]
    projects = [
        make_project(path="/home/user/project1"),
        make_project(computer="remote", path="/home/user/project2"),
    ]
    tree = build_tree(computers, projects, [])

    assert len(tree) == 2
    assert tree[0].data.computer.name == "local"
    assert tree[1].data.computer.name == "remote"
    assert len(tree[0].children) == 1
    assert len(tree[1].children) == 1


def test_build_tree_sets_parent_references():
    """Test that build_tree sets parent references correctly."""
    computers = [make_computer()]
    projects = [make_project()]
    sessions = [
        make_session("sess-parent", title="Parent"),
        make_session("sess-child", title="Child", initiator_session_id="sess-parent"),
    ]
    tree = build_tree(computers, projects, sessions)

    computer_node = tree[0]
    project_node = computer_node.children[0]
    parent_session = project_node.children[0]
    child_session = parent_session.children[0]

    assert computer_node.parent is None
    assert project_node.parent == computer_node
    assert parent_session.parent == project_node
    assert child_session.parent == parent_session


def test_build_tree_orphaned_session():
    """Test build_tree promotes orphaned sessions to root."""
    computers = [make_computer()]
    projects = [make_project()]
    sessions = [
        make_session("sess-orphan", title="Orphan", initiator_session_id="nonexistent"),
    ]
    tree = build_tree(computers, projects, sessions)

    # Orphaned session should appear as a root session
    project_node = tree[0].children[0]
    assert len(project_node.children) == 1
