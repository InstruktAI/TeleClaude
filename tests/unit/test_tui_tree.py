"""Unit tests for TUI tree building."""

# type: ignore - test fixtures use concrete types that are compatible

import pytest

from teleclaude.cli.tui.tree import TreeNode, build_tree


def test_build_tree_empty_inputs():
    """Test build_tree with no data."""
    tree = build_tree([], [], [])
    assert tree == []


def test_build_tree_single_computer_no_projects():
    """Test build_tree with computer but no projects."""
    computers: list[dict[str, object]] = [{"name": "local", "host": "localhost"}]  # guard: loose-dict
    tree = build_tree(computers, [], [])

    assert len(tree) == 1
    assert tree[0].type == "computer"
    assert tree[0].data["name"] == "local"
    assert tree[0].depth == 0
    assert len(tree[0].children) == 0


def test_build_tree_computer_with_project_no_sessions():
    """Test build_tree with computer and project but no sessions."""
    computers = [{"name": "local", "host": "localhost"}]
    projects = [{"computer": "local", "path": "/home/user/project"}]
    tree = build_tree(computers, projects, [])

    assert len(tree) == 1
    assert tree[0].type == "computer"
    assert len(tree[0].children) == 1

    project_node = tree[0].children[0]
    assert project_node.type == "project"
    assert project_node.data["path"] == "/home/user/project"
    assert project_node.depth == 1
    assert len(project_node.children) == 0


def test_build_tree_with_top_level_session():
    """Test build_tree with a top-level session (no initiator)."""
    computers = [{"name": "local", "host": "localhost"}]
    projects = [{"computer": "local", "path": "/home/user/project"}]
    sessions = [
        {
            "session_id": "sess-1",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Main Session",
            "initiator_session_id": None,
        }
    ]
    tree = build_tree(computers, projects, sessions)

    project_node = tree[0].children[0]
    assert len(project_node.children) == 1

    session_node = project_node.children[0]
    assert session_node.type == "session"
    assert session_node.data["session_id"] == "sess-1"
    assert session_node.data["title"] == "Main Session"
    assert session_node.depth == 2


def test_build_tree_with_ai_to_ai_nesting():
    """Test build_tree with AI-to-AI session nesting (initiator-worker)."""
    computers = [{"name": "local", "host": "localhost"}]
    projects = [{"computer": "local", "path": "/home/user/project"}]
    sessions = [
        {
            "session_id": "sess-parent",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Parent Session",
            "initiator_session_id": None,
        },
        {
            "session_id": "sess-child",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Child Session",
            "initiator_session_id": "sess-parent",
        },
    ]
    tree = build_tree(computers, projects, sessions)

    project_node = tree[0].children[0]
    assert len(project_node.children) == 1

    parent_session = project_node.children[0]
    assert parent_session.data["session_id"] == "sess-parent"
    assert len(parent_session.children) == 1

    child_session = parent_session.children[0]
    assert child_session.data["session_id"] == "sess-child"
    assert child_session.data["initiator_session_id"] == "sess-parent"
    assert child_session.depth == 3


def test_build_tree_with_deep_nesting():
    """Test build_tree with multiple levels of AI-to-AI nesting."""
    computers = [{"name": "local", "host": "localhost"}]
    projects = [{"computer": "local", "path": "/home/user/project"}]
    sessions = [
        {
            "session_id": "sess-1",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Level 1",
            "initiator_session_id": None,
        },
        {
            "session_id": "sess-2",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Level 2",
            "initiator_session_id": "sess-1",
        },
        {
            "session_id": "sess-3",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Level 3",
            "initiator_session_id": "sess-2",
        },
    ]
    tree = build_tree(computers, projects, sessions)

    project_node = tree[0].children[0]
    sess1 = project_node.children[0]
    sess2 = sess1.children[0]
    sess3 = sess2.children[0]

    assert sess1.depth == 2
    assert sess2.depth == 3
    assert sess3.depth == 4
    assert sess3.data["session_id"] == "sess-3"


def test_build_tree_multiple_computers():
    """Test build_tree with multiple computers."""
    computers = [
        {"name": "local", "host": "localhost"},
        {"name": "remote", "host": "192.168.1.10"},
    ]
    projects = [
        {"computer": "local", "path": "/home/user/project1"},
        {"computer": "remote", "path": "/home/user/project2"},
    ]
    tree = build_tree(computers, projects, [])

    assert len(tree) == 2
    assert tree[0].data["name"] == "local"
    assert tree[1].data["name"] == "remote"
    assert len(tree[0].children) == 1
    assert len(tree[1].children) == 1


def test_build_tree_sets_parent_references():
    """Test that build_tree sets parent references correctly."""
    computers = [{"name": "local", "host": "localhost"}]
    projects = [{"computer": "local", "path": "/home/user/project"}]
    sessions = [
        {
            "session_id": "sess-parent",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Parent",
            "initiator_session_id": None,
        },
        {
            "session_id": "sess-child",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Child",
            "initiator_session_id": "sess-parent",
        },
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
    """Test build_tree handles orphaned sessions (initiator doesn't exist)."""
    computers = [{"name": "local", "host": "localhost"}]
    projects = [{"computer": "local", "path": "/home/user/project"}]
    sessions = [
        {
            "session_id": "sess-orphan",
            "computer": "local",
            "working_directory": "/home/user/project",
            "title": "Orphan",
            "initiator_session_id": "nonexistent",
        }
    ]
    tree = build_tree(computers, projects, sessions)

    # Orphaned session won't appear since its initiator doesn't exist
    # (it's not a root session)
    project_node = tree[0].children[0]
    assert len(project_node.children) == 0
