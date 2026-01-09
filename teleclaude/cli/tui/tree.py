"""Build project-centric tree from API data."""

from dataclasses import dataclass, field


@dataclass
class TreeNode:
    """Node in the display tree."""

    type: str  # "computer", "project", "session", "todo"
    data: dict[str, object]  # guard: loose-dict
    depth: int
    children: list["TreeNode"] = field(default_factory=list)
    parent: "TreeNode | None" = None


def build_tree(
    computers: list[dict[str, object]],  # guard: loose-dict
    projects: list[dict[str, object]],  # guard: loose-dict
    sessions: list[dict[str, object]],  # guard: loose-dict
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
    sessions_by_initiator: dict[str, list[dict[str, object]]] = {}  # guard: loose-dict
    root_sessions: list[dict[str, object]] = []  # guard: loose-dict

    for session in sessions:
        initiator_id = session.get("initiator_session_id")
        if initiator_id and isinstance(initiator_id, str):
            sessions_by_initiator.setdefault(initiator_id, []).append(session)
        else:
            root_sessions.append(session)

    for computer in computers:
        comp_node = TreeNode(
            type="computer",
            data=computer,
            depth=0,
            children=[],
        )

        comp_name = computer.get("name", "")
        comp_projects = [p for p in projects if p.get("computer") == comp_name]

        for project in comp_projects:
            proj_node = TreeNode(
                type="project",
                data=project,
                depth=1,
                children=[],
                parent=comp_node,
            )

            # Get root sessions for this project
            proj_path = project.get("path", "")
            proj_sessions = [
                s for s in root_sessions if s.get("computer") == comp_name and s.get("working_directory") == proj_path
            ]

            for idx, session in enumerate(proj_sessions, 1):
                sess_node = _build_session_node(session, idx, 2, proj_node, sessions_by_initiator)
                proj_node.children.append(sess_node)

            comp_node.children.append(proj_node)

        tree.append(comp_node)

    return tree


def _build_session_node(
    session: dict[str, object],  # guard: loose-dict
    index: int | str,
    depth: int,
    parent: TreeNode,
    sessions_by_initiator: dict[str, list[dict[str, object]]],  # guard: loose-dict
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
    session_data = {**session, "display_index": str(index)}
    node = TreeNode(
        type="session",
        data=session_data,
        depth=depth,
        children=[],
        parent=parent,
    )

    # Add child sessions (AI-to-AI delegation)
    session_id = session.get("session_id")
    if session_id and isinstance(session_id, str):
        child_sessions = sessions_by_initiator.get(session_id, [])
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
