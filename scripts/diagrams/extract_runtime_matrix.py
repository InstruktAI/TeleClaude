#!/usr/bin/env python3
"""Extract runtime feature matrix from HOOK_EVENT_MAP, adapters, and agent config."""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "teleclaude" / "core" / "events.py"
AGENT_TYPES_PATH = PROJECT_ROOT / "teleclaude" / "helpers" / "agent_types.py"
AGENTS_PATH = PROJECT_ROOT / "teleclaude" / "core" / "agents.py"
ADAPTERS_DIR = PROJECT_ROOT / "teleclaude" / "adapters"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "runtime-matrix.mmd"


def parse_hook_event_counts(tree: ast.Module) -> dict[str, int]:
    """Count events per runtime from HOOK_EVENT_MAP."""
    counts: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AgentHookEvents":
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.target.id == "HOOK_EVENT_MAP" and item.value:
                        counts = _count_map_entries(item.value)
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "HOOK_EVENT_MAP":
                            counts = _count_map_entries(item.value)
    return counts


def _count_map_entries(node: ast.expr) -> dict[str, int]:
    """Count entries in the nested HOOK_EVENT_MAP structure."""
    counts: dict[str, int] = {}

    # Unwrap MappingProxyType(...)
    inner = node
    if isinstance(node, ast.Call) and node.args:
        inner = node.args[0]

    if not isinstance(inner, ast.Dict):
        return counts

    for key, val in zip(inner.keys, inner.values):
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            runtime = key.value
            inner_dict = val
            if isinstance(val, ast.Call) and val.args:
                inner_dict = val.args[0]
            if isinstance(inner_dict, ast.Dict):
                counts[runtime] = len(inner_dict.keys)

    return counts


def parse_agent_names(tree: ast.Module) -> list[str]:
    """Extract AgentName enum values."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AgentName":
            names: list[str] = []
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and isinstance(item.value, ast.Constant):
                            names.append(str(item.value.value))
            return names
    return []


def detect_adapter_features() -> dict[str, list[str]]:
    """Scan adapter files for feature indicators."""
    features: dict[str, list[str]] = {}

    for py_file in ADAPTERS_DIR.glob("*.py"):
        if py_file.name == "__init__.py":
            continue

        content = py_file.read_text(encoding="utf-8")
        adapter_name = py_file.stem.replace("_adapter", "")

        detected: list[str] = []
        if "async def" in content:
            detected.append("async")
        if "send_message" in content or "send_request" in content:
            detected.append("messaging")
        if "polling" in content.lower() or "poll" in content.lower():
            detected.append("polling")
        if "threaded" in content.lower():
            detected.append("threaded_output")

        features[adapter_name] = detected

    return features


def detect_agent_config_features() -> dict[str, list[str]]:
    """Scan agents.py for per-agent features (resume, continue, exec)."""
    if not AGENTS_PATH.exists():
        return {}

    content = AGENTS_PATH.read_text(encoding="utf-8")
    features: dict[str, list[str]] = {}

    # Check for resume_template usage
    if "resume_template" in content:
        features.setdefault("all", []).append("resume")
    if "continue_template" in content:
        features.setdefault("all", []).append("continue")
    if "exec_subcommand" in content:
        features.setdefault("codex", []).append("exec_mode")
    if "interactive_flag" in content:
        features.setdefault("all", []).append("interactive")

    return features


def generate_mermaid(
    event_counts: dict[str, int],
    agent_names: list[str],
    adapter_features: dict[str, list[str]],
) -> str:
    """Generate Mermaid diagram showing runtime feature matrix."""
    lines: list[str] = [
        "---",
        "title: Runtime Feature Matrix",
        "---",
        "flowchart LR",
    ]

    # Agent nodes with event counts
    for agent in agent_names:
        count = event_counts.get(agent, 0)
        hook_label = f"{count} hook events" if count else "no hooks"
        lines.append(f'    {agent}["{agent}<br/>{hook_label}"]')

    lines.append("")

    # Feature nodes
    all_features: set[str] = set()
    for feats in adapter_features.values():
        all_features.update(feats)

    for feat in sorted(all_features):
        safe_feat = feat.replace(" ", "_")
        lines.append(f"    feat_{safe_feat}({feat})")

    lines.append("")

    # Hook event detail per runtime
    for agent in agent_names:
        count = event_counts.get(agent, 0)
        if count:
            lines.append(f"    {agent} --> hooks_{agent}[{count} native events mapped]")

    lines.append("")

    # Adapter feature edges
    for adapter, feats in adapter_features.items():
        # Find matching agent
        agent_match = None
        for agent in agent_names:
            if agent in adapter:
                agent_match = agent
                break
        if not agent_match:
            continue
        for feat in feats:
            safe_feat = feat.replace(" ", "_")
            lines.append(f"    {agent_match} --> feat_{safe_feat}")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not EVENTS_PATH.exists():
        print(f"ERROR: {EVENTS_PATH} not found", file=sys.stderr)
        sys.exit(1)

    events_tree = ast.parse(EVENTS_PATH.read_text(encoding="utf-8"), filename=str(EVENTS_PATH))

    agent_tree = None
    if AGENT_TYPES_PATH.exists():
        agent_tree = ast.parse(AGENT_TYPES_PATH.read_text(encoding="utf-8"), filename=str(AGENT_TYPES_PATH))

    event_counts = parse_hook_event_counts(events_tree)
    agent_names = parse_agent_names(agent_tree) if agent_tree else list(event_counts.keys())
    adapter_features = detect_adapter_features()

    if not event_counts:
        print("WARNING: No HOOK_EVENT_MAP entries found", file=sys.stderr)

    mermaid = generate_mermaid(event_counts, agent_names, adapter_features)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
