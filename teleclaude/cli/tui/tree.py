"""Build project-centric tree from API data."""

from dataclasses import dataclass, field
from typing import TypeGuard

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo
from teleclaude.cli.tui.types import NodeType


@dataclass(frozen=True)
class ComputerDisplayInfo:
    """Computer info with display-only counts."""

    computer: ComputerInfo
    session_count: int
    recent_activity: bool


@dataclass(frozen=True)
class SessionDisplayInfo:
    """Session info with display index for tree rendering."""

    session: SessionInfo
    display_index: str


@dataclass
class ComputerNode:
    type: NodeType
    data: ComputerDisplayInfo
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


@dataclass
class ProjectNode:
    type: NodeType
    data: ProjectInfo
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


@dataclass
class SessionNode:
    type: NodeType
    data: SessionDisplayInfo
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


TreeNode = ComputerNode | ProjectNode | SessionNode


def is_computer_node(node: TreeNode) -> TypeGuard[ComputerNode]:
    """Return True when the tree node is a computer node."""
    return node.type == NodeType.COMPUTER


def is_project_node(node: TreeNode) -> TypeGuard[ProjectNode]:
    """Return True when the tree node is a project node."""
    return node.type == NodeType.PROJECT


def is_session_node(node: TreeNode) -> TypeGuard[SessionNode]:
    """Return True when the tree node is a session node."""
    return node.type == NodeType.SESSION


def build_tree(
    computers: list[ComputerDisplayInfo],
    projects: list[ProjectInfo],
    sessions: list[SessionInfo],
) -> list[TreeNode]:
    """Build hierarchical tree for display.

    Structure: Computer → Project → Session (with AI-to-AI nesting)

    Args:
        computers: List of online computers
        projects: List of projects
        sessions: List of sessions

    Returns:
        List of root tree nodes
    """
    tree: list[TreeNode] = []

    # Build a stable computer list for rendering. Some session feeds can contain
    # sessions for computers that are temporarily missing from the computers
    # list (e.g. stale heartbeat windows). Those sessions should still render.
    all_computers = list(computers)
    known_computers = {entry.computer.name for entry in computers}
    for session in sessions:
        computer_name = (session.computer or "").strip()
        if not computer_name or computer_name in known_computers:
            continue
        known_computers.add(computer_name)
        all_computers.append(
            ComputerDisplayInfo(
                computer=ComputerInfo(
                    name=computer_name,
                    status="offline",
                    user=None,
                    host=None,
                    is_local=(computer_name == "local"),
                    tmux_binary=None,
                ),
                session_count=0,
                recent_activity=False,
            )
        )

    # Index sessions by initiator for AI-to-AI nesting
    sessions_by_initiator: dict[str, list[SessionInfo]] = {}
    root_sessions: list[SessionInfo] = []

    session_ids = {s.session_id for s in sessions}
    for session in sessions:
        initiator_id = session.initiator_session_id
        if initiator_id and initiator_id in session_ids:
            sessions_by_initiator.setdefault(initiator_id, []).append(session)
        else:
            root_sessions.append(session)

    for computer in all_computers:
        comp_node = ComputerNode(
            type=NodeType.COMPUTER,
            data=computer,
            depth=0,
            children=[],
        )

        comp_name = computer.computer.name
        comp_projects = [p for p in projects if p.computer == comp_name]

        # Track matched sessions to find orphans later
        matched_session_ids: set[str] = set()

        for project in comp_projects:
            proj_node = ProjectNode(
                type=NodeType.PROJECT,
                data=project,
                depth=1,
                children=[],
                parent=comp_node,
            )

            # Get root sessions for this project
            proj_path = project.path
            proj_sessions = [s for s in root_sessions if s.computer == comp_name and s.project_path == proj_path]

            for idx, session in enumerate(proj_sessions, 1):
                sess_node = _build_session_node(session, idx, 2, proj_node, sessions_by_initiator)
                proj_node.children.append(sess_node)
                matched_session_ids.add(session.session_id)

            comp_node.children.append(proj_node)

        # Find orphan sessions (not matched to any project) and group by project_path
        orphan_sessions = [
            s for s in root_sessions if s.computer == comp_name and s.session_id not in matched_session_ids
        ]

        # Group orphans by their project_path to create project nodes
        orphans_by_path: dict[str, list[SessionInfo]] = {}
        for session in orphan_sessions:
            proj_path = session.project_path or ""
            orphans_by_path.setdefault(proj_path, []).append(session)

        # Create project nodes for each unique project_path
        for proj_path, proj_sessions in orphans_by_path.items():
            proj_node = ProjectNode(
                type="project",
                data=ProjectInfo(computer=comp_name, name="", path=proj_path, description=None),
                depth=1,
                children=[],
                parent=comp_node,
            )

            for idx, session in enumerate(proj_sessions, 1):
                sess_node = _build_session_node(session, idx, 2, proj_node, sessions_by_initiator)
                proj_node.children.append(sess_node)

            comp_node.children.append(proj_node)

        tree.append(comp_node)

    return tree


def _build_session_node(
    session: SessionInfo,
    index: int | str,
    depth: int,
    parent: TreeNode,
    sessions_by_initiator: dict[str, list[SessionInfo]],
) -> TreeNode:
    """Recursively build session node with AI-to-AI children.

    Args:
        session: Session data
        index: Display index (e.g., 1, "1.1", "1.2")
        depth: Tree depth
        parent: Parent node
        sessions_by_initiator: Map of initiator_session_id -> child sessions

    Returns:
        Session tree node with children
    """
    session_data = SessionDisplayInfo(session=session, display_index=str(index))
    node = SessionNode(
        type=NodeType.SESSION,
        data=session_data,
        depth=depth,
        children=[],
        parent=parent,
    )

    # Add child sessions (AI-to-AI delegation)
    session_id = session.session_id
    child_sessions = sessions_by_initiator.get(session_id, [])
    if child_sessions:
        for child_idx, child in enumerate(child_sessions, 1):
            child_node = _build_session_node(
                child,
                f"{index}.{child_idx}",
                depth + 1,
                node,
                sessions_by_initiator,
            )
            node.children.append(child_node)

    return node
