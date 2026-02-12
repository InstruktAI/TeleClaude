#!/usr/bin/env python3
"""Extract event flow diagram from events.py and agent_coordinator.py."""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "teleclaude" / "core" / "events.py"
COORDINATOR_PATH = PROJECT_ROOT / "teleclaude" / "core" / "agent_coordinator.py"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "event-flow.mmd"


def parse_agent_hook_constants(tree: ast.Module) -> dict[str, str]:
    """Extract AgentHookEvents class string constants."""
    constants: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AgentHookEvents":
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.value and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                        constants[item.target.id] = item.value.value
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if (
                            isinstance(target, ast.Name)
                            and isinstance(item.value, ast.Constant)
                            and isinstance(item.value.value, str)
                        ):
                            constants[target.id] = item.value.value
    return constants


def parse_hook_event_map(tree: ast.Module) -> dict[str, dict[str, str]]:
    """Extract HOOK_EVENT_MAP from AgentHookEvents class.

    Returns {runtime: {native_event: internal_event}}.
    """
    attr_values = parse_agent_hook_constants(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AgentHookEvents":
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
    """Parse nested MappingProxyType dict structure."""
    result: dict[str, dict[str, str]] = {}

    inner = node
    if isinstance(node, ast.Call) and isinstance(node.args[0] if node.args else None, ast.Dict):
        inner = node.args[0]

    if not isinstance(inner, ast.Dict):
        return result

    for key, val in zip(inner.keys, inner.values):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        runtime = key.value

        inner_dict = val
        if isinstance(val, ast.Call) and val.args:
            inner_dict = val.args[0]

        if isinstance(inner_dict, ast.Dict):
            mapping: dict[str, str] = {}
            for native_key, internal_value in zip(inner_dict.keys, inner_dict.values):
                if isinstance(native_key, ast.Constant) and isinstance(native_key.value, str):
                    event_val = _resolve_attr(internal_value, attr_values)
                    if event_val:
                        mapping[native_key.value] = event_val
            result[runtime] = mapping

    return result


def _resolve_attr(node: ast.expr, attr_values: dict[str, str]) -> str | None:
    """Resolve class attribute reference or constant to a string value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in attr_values:
        return attr_values[node.id]
    if isinstance(node, ast.Attribute) and node.attr in attr_values:
        return attr_values[node.attr]
    return None


def parse_handler_dispatch(tree: ast.Module) -> dict[str, str]:
    """Extract AgentHookEvents constant -> handler method mapping from handle_event()."""
    dispatch: dict[str, str] = {}

    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "AgentCoordinator"):
            continue

        for class_item in node.body:
            if not (
                isinstance(class_item, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_item.name == "handle_event"
            ):
                continue

            for stmt in class_item.body:
                _collect_dispatch_from_stmt(stmt, dispatch)

    return dispatch


def _collect_dispatch_from_stmt(stmt: ast.stmt, dispatch: dict[str, str]) -> None:
    """Collect event dispatch from if/elif blocks in handle_event."""
    if not isinstance(stmt, ast.If):
        return

    event_constant = _extract_event_constant(stmt.test)
    handler_name = _extract_handler_call(stmt.body)

    if event_constant and handler_name:
        dispatch[event_constant] = handler_name

    for orelse_stmt in stmt.orelse:
        _collect_dispatch_from_stmt(orelse_stmt, dispatch)


def _extract_event_constant(test: ast.expr) -> str | None:
    """Extract AgentHookEvents.<CONST> from compare expression."""
    if not isinstance(test, ast.Compare):
        return None
    if len(test.ops) != 1 or len(test.comparators) != 1:
        return None

    comparator = test.comparators[0]
    if isinstance(comparator, ast.Attribute) and isinstance(comparator.value, ast.Name):
        if comparator.value.id == "AgentHookEvents":
            return comparator.attr

    return None


def _extract_handler_call(body: list[ast.stmt]) -> str | None:
    """Extract self.handle_* method name called in branch body."""
    for stmt in body:
        call_expr: ast.Call | None = None

        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Await) and isinstance(stmt.value.value, ast.Call):
            call_expr = stmt.value.value
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call_expr = stmt.value

        if call_expr and isinstance(call_expr.func, ast.Attribute) and isinstance(call_expr.func.value, ast.Name):
            if call_expr.func.value.id == "self":
                return call_expr.func.attr

    return None


def generate_mermaid(
    hook_map: dict[str, dict[str, str]],
    handler_dispatch: dict[str, str],
    event_constants: dict[str, str],
) -> str:
    """Generate Mermaid flowchart for runtime -> event -> handler flow."""
    lines: list[str] = [
        "---",
        "title: Event Flow",
        "---",
        "flowchart LR",
    ]

    internal_events: set[str] = set()
    for runtime_map in hook_map.values():
        internal_events.update(runtime_map.values())

    for runtime in hook_map:
        lines.append(f"    {runtime}[{runtime}]")

    lines.append("")

    for event in sorted(internal_events):
        safe_id = event.replace(" ", "_")
        lines.append(f"    {safe_id}({event})")

    lines.append("")

    handler_names = sorted(set(handler_dispatch.values()))
    for handler in handler_names:
        lines.append(f"    h_{handler}[/{handler}/]")

    lines.append("")

    for runtime, mapping in hook_map.items():
        for native_event, internal_event in mapping.items():
            safe_internal = internal_event.replace(" ", "_")
            lines.append(f"    {runtime} -->|{native_event}| {safe_internal}")

    lines.append("")

    for event_constant, handler_name in sorted(handler_dispatch.items()):
        internal_event = event_constants.get(event_constant)
        if not internal_event:
            continue
        safe_internal = internal_event.replace(" ", "_")
        lines.append(f"    {safe_internal} --> h_{handler_name}")

    return "\n".join(lines) + "\n"


def main() -> None:
    for path in [EVENTS_PATH, COORDINATOR_PATH]:
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)

    events_tree = ast.parse(EVENTS_PATH.read_text(encoding="utf-8"), filename=str(EVENTS_PATH))
    coord_tree = ast.parse(COORDINATOR_PATH.read_text(encoding="utf-8"), filename=str(COORDINATOR_PATH))

    hook_map = parse_hook_event_map(events_tree)
    event_constants = parse_agent_hook_constants(events_tree)
    handler_dispatch = parse_handler_dispatch(coord_tree)

    if not hook_map:
        print("WARNING: No HOOK_EVENT_MAP found", file=sys.stderr)
    if not handler_dispatch:
        print("WARNING: No handler dispatch found", file=sys.stderr)

    mermaid = generate_mermaid(hook_map, handler_dispatch, event_constants)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
