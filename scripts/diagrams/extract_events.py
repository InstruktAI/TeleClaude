#!/usr/bin/env python3
"""Extract event flow diagram from events.py and agent_coordinator.py."""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "teleclaude" / "core" / "events.py"
COORDINATOR_PATH = PROJECT_ROOT / "teleclaude" / "core" / "agent_coordinator.py"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "event-flow.mmd"


def parse_literal_type(tree: ast.Module, name: str) -> list[str]:
    """Extract string values from a Literal type alias assignment."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return _extract_literal_values(node.value)
    return []


def _extract_literal_values(node: ast.expr) -> list[str]:
    """Recursively extract string constants from Literal[...] subscript."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Tuple):
        values: list[str] = []
        for elt in node.slice.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                values.append(elt.value)
        return values
    return []


def parse_hook_event_map(tree: ast.Module) -> dict[str, dict[str, str]]:
    """Extract HOOK_EVENT_MAP from AgentHookEvents class.

    Returns {runtime: {native_event: internal_event}}.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AgentHookEvents":
            # Collect class-level attribute values for resolving references
            # Attributes use AnnAssign (e.g. AGENT_SESSION_START: AgentHookEventType = "session_start")
            attr_values: dict[str, str] = {}
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.value and isinstance(item.value, ast.Constant):
                        attr_values[item.target.id] = str(item.value.value)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and isinstance(item.value, ast.Constant):
                            attr_values[target.id] = str(item.value.value)

            # Find HOOK_EVENT_MAP assignment (may be Assign or AnnAssign)
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.target.id == "HOOK_EVENT_MAP" and item.value:
                        return _parse_map_value(item.value, attr_values)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "HOOK_EVENT_MAP":
                            return _parse_map_value(item.value, attr_values)
    return {}


def _parse_map_value(node: ast.expr, attr_values: dict[str, str]) -> dict[str, dict[str, str]]:
    """Parse the nested MappingProxyType dict structure."""
    result: dict[str, dict[str, str]] = {}

    # Unwrap MappingProxyType(...)
    inner = node
    if isinstance(node, ast.Call) and isinstance(node.args[0] if node.args else None, ast.Dict):
        inner = node.args[0]

    if not isinstance(inner, ast.Dict):
        return result

    for key, val in zip(inner.keys, inner.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        runtime = key.value

        # Unwrap inner MappingProxyType(...)
        inner_dict = val
        if isinstance(val, ast.Call) and val.args:
            inner_dict = val.args[0]

        if isinstance(inner_dict, ast.Dict):
            mapping: dict[str, str] = {}
            for k, v in zip(inner_dict.keys, inner_dict.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    event_val = _resolve_attr(v, attr_values)
                    if event_val:
                        mapping[k.value] = event_val
            result[runtime] = mapping

    return result


def _resolve_attr(node: ast.expr, attr_values: dict[str, str]) -> str | None:
    """Resolve a class attribute reference or constant to its string value."""
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name) and node.id in attr_values:
        return attr_values[node.id]
    if isinstance(node, ast.Attribute) and node.attr in attr_values:
        return attr_values[node.attr]
    return None


def parse_handler_dispatch(tree: ast.Module) -> list[str]:
    """Extract event types handled by AgentCoordinator.handle_event()."""
    handlers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AgentCoordinator":
            for item in ast.walk(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "handle_event":
                    for child in ast.walk(item):
                        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                            if child.value.id == "AgentHookEvents":
                                handlers.append(child.attr)
    return handlers


def generate_mermaid(
    hook_map: dict[str, dict[str, str]],
    handlers: list[str],
) -> str:
    """Generate Mermaid flowchart for event flow."""
    lines: list[str] = [
        "---",
        "title: Event Flow",
        "---",
        "flowchart LR",
    ]

    # Collect all unique internal events
    internal_events: set[str] = set()
    for runtime_map in hook_map.values():
        internal_events.update(runtime_map.values())

    # Runtime nodes
    for runtime in hook_map:
        lines.append(f"    {runtime}[{runtime}]")

    lines.append("")

    # Internal event nodes
    for event in sorted(internal_events):
        safe_id = event.replace(" ", "_")
        lines.append(f"    {safe_id}({event})")

    lines.append("")

    # Handler nodes
    handler_set = set(handlers)
    for h in sorted(handler_set):
        safe_id = f"h_{h}"
        lines.append(f"    {safe_id}[/{h}/]")

    lines.append("")

    # Edges: runtime --> native event label --> internal event
    for runtime, mapping in hook_map.items():
        for native_event, internal_event in mapping.items():
            safe_internal = internal_event.replace(" ", "_")
            lines.append(f"    {runtime} -->|{native_event}| {safe_internal}")

    lines.append("")

    # Edges: internal event --> handler (match by name convention)
    handler_map = {
        "AGENT_SESSION_START": "handle_session_start",
        "USER_PROMPT_SUBMIT": "handle_user_prompt_submit",
        "TOOL_USE": "handle_tool_use",
        "TOOL_DONE": "handle_tool_done",
        "AGENT_STOP": "handle_agent_stop",
        "AGENT_NOTIFICATION": "handle_notification",
        "AGENT_SESSION_END": "handle_session_end",
    }

    for event in sorted(internal_events):
        safe_event = event.replace(" ", "_")
        for attr_name in handler_map:
            if attr_name in handler_set and event == _attr_to_value(attr_name):
                lines.append(f"    {safe_event} --> h_{attr_name}")

    return "\n".join(lines) + "\n"


def _attr_to_value(attr: str) -> str:
    """Convert AgentHookEvents attribute name to its likely string value."""
    mapping = {
        "AGENT_SESSION_START": "session_start",
        "USER_PROMPT_SUBMIT": "user_prompt_submit",
        "TOOL_USE": "tool_use",
        "TOOL_DONE": "tool_done",
        "AGENT_STOP": "agent_stop",
        "AGENT_NOTIFICATION": "notification",
        "AGENT_SESSION_END": "session_end",
        "AGENT_ERROR": "error",
    }
    return mapping.get(attr, attr.lower())


def main() -> None:
    for path in [EVENTS_PATH, COORDINATOR_PATH]:
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)

    events_tree = ast.parse(EVENTS_PATH.read_text(encoding="utf-8"), filename=str(EVENTS_PATH))
    coord_tree = ast.parse(COORDINATOR_PATH.read_text(encoding="utf-8"), filename=str(COORDINATOR_PATH))

    hook_map = parse_hook_event_map(events_tree)
    handlers = parse_handler_dispatch(coord_tree)

    if not hook_map:
        print("WARNING: No HOOK_EVENT_MAP found", file=sys.stderr)
    if not handlers:
        print("WARNING: No handler dispatch found", file=sys.stderr)

    mermaid = generate_mermaid(hook_map, handlers)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
