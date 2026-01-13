"""Build project-centric tree from API data."""

from dataclasses import dataclass, field
from typing import Literal

from teleclaude.cli.models import ComputerInfo, ProjectInfo, SessionInfo


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
    type: Literal["computer"]
    data: ComputerDisplayInfo
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


@dataclass
class ProjectNode:
    type: Literal["project"]
    data: ProjectInfo
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


@dataclass
class SessionNode:
    type: Literal["session"]
    data: SessionDisplayInfo
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


TreeNode = ComputerNode | ProjectNode | SessionNode


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

    # Index sessions by initiator for AI-to-AI nesting
    sessions_by_initiator: dict[str, list[SessionInfo]] = {}
    root_sessions: list[SessionInfo] = []

    for session in sessions:
        initiator_id = session.initiator_session_id
        if initiator_id:
            sessions_by_initiator.setdefault(initiator_id, []).append(session)
        else:
            root_sessions.append(session)

    for computer in computers:
        comp_node = ComputerNode(
            type="computer",
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
                type="project",
                data=project,
                depth=1,
                children=[],
                parent=comp_node,
            )

            # Get root sessions for this project
            proj_path = project.path
            proj_sessions = [s for s in root_sessions if s.computer == comp_name and s.working_directory == proj_path]

            for idx, session in enumerate(proj_sessions, 1):
                sess_node = _build_session_node(session, idx, 2, proj_node, sessions_by_initiator)
                proj_node.children.append(sess_node)
                matched_session_ids.add(session.session_id)

            comp_node.children.append(proj_node)

        # Find orphan sessions (not matched to any project) and group by working_directory
        orphan_sessions = [
            s for s in root_sessions if s.computer == comp_name and s.session_id not in matched_session_ids
        ]

        # Group orphans by their working_directory to create project nodes
        orphans_by_path: dict[str, list[SessionInfo]] = {}
        for session in orphan_sessions:
            wd = session.working_directory
            orphans_by_path.setdefault(wd, []).append(session)

        # Create project nodes for each unique working_directory
        for wd_path, wd_sessions in orphans_by_path.items():
            proj_node = ProjectNode(
                type="project",
                data=ProjectInfo(computer=comp_name, name="", path=wd_path, description=None),
                depth=1,
                children=[],
                parent=comp_node,
            )

            for idx, session in enumerate(wd_sessions, 1):
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
        type="session",
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
