"""Build project-centric tree from API data."""

import os
from dataclasses import dataclass, field
from typing import TypeGuard

from teleclaude.api_models import ComputerDTO, ProjectDTO, SessionDTO
from teleclaude.cli.tui.types import NodeType
from teleclaude.constants import WORKTREE_DIR


def project_collapse_key(computer: str | None, path: str) -> tuple[str, str]:
    """Identity of a project for collapse state and persistence.

    Keyed by computer and path together: the same path can exist on more than
    one computer, so path alone would collide across machines.
    """
    return (computer or "local", path)


def parse_collapsed_projects(value: object) -> set[tuple[str, str]]:
    """Parse persisted collapsed-project identities.

    Accepts the current ``[computer, path]`` pair form and the legacy bare-path
    string form (whose computer defaults to local).
    """
    if not isinstance(value, list):
        return set()
    parsed: set[tuple[str, str]] = set()
    for item in value:
        if isinstance(item, str):
            parsed.add(("local", item))
        elif isinstance(item, list | tuple) and len(item) == 2:
            parsed.add((str(item[0]), str(item[1])))
    return parsed


@dataclass(frozen=True)
class ComputerDisplayInfo:
    """Computer info with display-only counts."""

    computer: ComputerDTO
    session_count: int
    recent_activity: bool


@dataclass(frozen=True)
class SessionDisplayInfo:
    """Session info with display index for tree rendering."""

    session: SessionDTO
    display_index: str


@dataclass
class ComputerNode:
    """A tree node representing a computer."""

    type: NodeType
    data: ComputerDisplayInfo
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


@dataclass
class ProjectNode:
    """A tree node representing a project."""

    type: NodeType
    data: ProjectDTO
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


@dataclass
class SessionNode:
    """A tree node representing a session."""

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


def _base_project_path(project_path: str) -> str:
    """Extract base project path, stripping any worktree suffix.

    A worktree path like ``/repo/trees/my-task`` resolves to ``/repo``.
    A plain project path is returned unchanged.
    """
    marker = os.sep + WORKTREE_DIR + os.sep
    idx = project_path.find(marker)
    if idx != -1:
        return project_path[:idx]
    return project_path


def _same_project(path_a: str | None, path_b: str | None) -> bool:
    """Return True when both paths resolve to the same base project."""
    if not path_a or not path_b:
        return path_a == path_b
    return _base_project_path(path_a) == _base_project_path(path_b)


def _created_at_key(session: SessionDTO) -> str:
    """Null-safe sort key: the session's own ``created_at``.

    Every sibling level — root sessions, AI-to-AI children, and project groups —
    ranks by this, matching the flat ``created_at`` desc feed sort. A node's
    position is its own creation time and nothing else; a newer descendant never
    lifts its parent.
    """
    return session.created_at or ""


def _newest_created_at(sessions: list[SessionDTO]) -> str:
    """Return the newest own ``created_at`` across a list of sessions; "" when empty."""
    return max((s.created_at or "" for s in sessions), default="")


def build_tree(
    computers: list[ComputerDisplayInfo],
    projects: list[ProjectDTO],
    sessions: list[SessionDTO],
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
                computer=ComputerDTO(
                    name=computer_name,
                    status="reconnecting",
                    user=None,
                    host=None,
                    is_local=(computer_name == "local"),
                ),
                session_count=0,
                recent_activity=False,
            )
        )

    # Index sessions by initiator for AI-to-AI nesting.
    # Only nest when child belongs to the same project as the initiator;
    # cross-project children render as top-level nodes in their own project.
    sessions_by_initiator: dict[str, list[SessionDTO]] = {}
    root_sessions: list[SessionDTO] = []

    session_lookup = {s.session_id: s for s in sessions}
    for session in sessions:
        initiator_id = session.initiator_session_id
        if initiator_id and initiator_id in session_lookup and not session.detached:
            initiator = session_lookup[initiator_id]
            if _same_project(session.project_path, initiator.project_path):
                sessions_by_initiator.setdefault(initiator_id, []).append(session)
            else:
                root_sessions.append(session)
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
        # Sort projects by path length descending so most-specific matches first
        comp_projects_sorted = sorted(comp_projects, key=lambda p: len(p.path), reverse=True)

        # Track matched sessions to find orphans later
        matched_session_ids: set[str] = set()

        # Match sessions to most-specific project via prefix
        project_sessions: dict[str, list[SessionDTO]] = {p.path: [] for p in comp_projects}
        for s in root_sessions:
            if s.computer != comp_name or not s.project_path:
                continue
            for p in comp_projects_sorted:
                worktree_prefix = p.path + os.sep + WORKTREE_DIR + os.sep
                if s.project_path == p.path or s.project_path.startswith(worktree_prefix):
                    project_sessions[p.path].append(s)
                    matched_session_ids.add(s.session_id)
                    break

        # Order projects by their newest session's own created_at (desc) so a
        # project with recent work surfaces; projects with no sessions sort last
        # in a stable order.
        comp_projects_by_recency = sorted(
            comp_projects,
            key=lambda p: _newest_created_at(project_sessions[p.path]),
            reverse=True,
        )
        for project in comp_projects_by_recency:
            proj_node = ProjectNode(
                type=NodeType.PROJECT,
                data=project,
                depth=1,
                children=[],
                parent=comp_node,
            )

            ordered_sessions = sorted(
                project_sessions[project.path],
                key=_created_at_key,
                reverse=True,
            )
            for idx, session in enumerate(ordered_sessions, 1):
                sess_node = _build_session_node(session, idx, 2, proj_node, sessions_by_initiator)
                proj_node.children.append(sess_node)

            comp_node.children.append(proj_node)

        # Find orphan sessions (not matched to any project) and group by project_path
        orphan_sessions = [
            s for s in root_sessions if s.computer == comp_name and s.session_id not in matched_session_ids
        ]

        # Group orphans by their project_path to create project nodes
        orphans_by_path: dict[str, list[SessionDTO]] = {}
        for session in orphan_sessions:
            proj_path = session.project_path or ""
            orphans_by_path.setdefault(proj_path, []).append(session)

        # Create project nodes for each unique project_path, newest session first
        orphans_by_recency = sorted(
            orphans_by_path.items(),
            key=lambda item: _newest_created_at(item[1]),
            reverse=True,
        )
        for proj_path, proj_sessions in orphans_by_recency:
            proj_node = ProjectNode(
                type=NodeType.PROJECT,
                data=ProjectDTO(computer=comp_name, name="", path=proj_path, description=None),
                depth=1,
                children=[],
                parent=comp_node,
            )

            ordered_sessions = sorted(
                proj_sessions,
                key=_created_at_key,
                reverse=True,
            )
            for idx, session in enumerate(ordered_sessions, 1):
                sess_node = _build_session_node(session, idx, 2, proj_node, sessions_by_initiator)
                proj_node.children.append(sess_node)

            comp_node.children.append(proj_node)

        tree.append(comp_node)

    return tree


def _build_session_node(
    session: SessionDTO,
    index: int | str,
    depth: int,
    parent: TreeNode,
    sessions_by_initiator: dict[str, list[SessionDTO]],
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
        ordered_children = sorted(
            child_sessions,
            key=_created_at_key,
            reverse=True,
        )
        for child_idx, child in enumerate(ordered_children, 1):
            child_node = _build_session_node(
                child,
                f"{index}.{child_idx}",
                depth + 1,
                node,
                sessions_by_initiator,
            )
            node.children.append(child_node)

    return node
