#!/usr/bin/env python3
"""Extract runtime feature matrix from hook mappings, hook adapters, and agent protocol."""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = PROJECT_ROOT / "teleclaude" / "core" / "events.py"
AGENT_TYPES_PATH = PROJECT_ROOT / "teleclaude" / "helpers" / "agent_types.py"
CONSTANTS_PATH = PROJECT_ROOT / "teleclaude" / "constants.py"
HOOK_ADAPTERS_DIR = PROJECT_ROOT / "teleclaude" / "hooks" / "adapters"
HOOK_RECEIVER_PATH = PROJECT_ROOT / "teleclaude" / "hooks" / "receiver.py"
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


def detect_adapter_features(agent_names: list[str]) -> dict[str, list[str]]:
    """Scan teleclaude/hooks/adapters/{agent}.py for runtime adapter capabilities."""
    features: dict[str, list[str]] = {}

    for agent in agent_names:
        adapter_path = HOOK_ADAPTERS_DIR / f"{agent}.py"
        if not adapter_path.exists():
            continue

        content = adapter_path.read_text(encoding="utf-8")
        detected: set[str] = set()

        if "def normalize_payload" in content:
            detected.add("hook_normalization")
        if "session_id=" in content:
            detected.add("session_tracking")
        if "transcript_path=" in content:
            detected.add("transcript_path")
        if "_discover_transcript_path" in content:
            detected.add("transcript_discovery")
        if "prompt=" in content:
            detected.add("prompt_capture")
        if "message=" in content:
            detected.add("notification_capture")

        features[agent] = sorted(detected)

    return features


def parse_agent_protocol_features(tree: ast.Module) -> dict[str, list[str]]:
    """Extract per-agent protocol features from AGENT_PROTOCOL in constants.py."""
    protocol_features: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "AGENT_PROTOCOL" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue

        for key_node, value_node in zip(node.value.keys, node.value.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            agent = key_node.value
            if not isinstance(value_node, ast.Dict):
                continue

            features: set[str] = set()
            dict_entries: dict[str, ast.expr] = {}
            for inner_key, inner_value in zip(value_node.keys, value_node.values):
                if isinstance(inner_key, ast.Constant) and isinstance(inner_key.value, str):
                    dict_entries[inner_key.value] = inner_value

            model_flags = dict_entries.get("model_flags")
            if isinstance(model_flags, ast.Dict) and model_flags.keys:
                features.add("model_tiers")

            exec_subcommand = _extract_constant_string(dict_entries.get("exec_subcommand"))
            if exec_subcommand:
                features.add("exec_mode")

            resume_template = _extract_constant_string(dict_entries.get("resume_template"))
            if resume_template:
                features.add("resume")

            continue_template = _extract_constant_string(dict_entries.get("continue_template"))
            if continue_template:
                features.add("continue")

            interactive_flag = _extract_constant_string(dict_entries.get("interactive_flag"))
            if interactive_flag:
                features.add("interactive")

            if features:
                protocol_features[agent] = sorted(features)

    return protocol_features


def detect_checkpoint_blocking_features(agent_names: list[str]) -> dict[str, bool]:
    """Detect whether runtime can block hook stop events in receiver checkpoint path."""
    blocking: dict[str, bool] = {agent: True for agent in agent_names}
    if not HOOK_RECEIVER_PATH.exists():
        return blocking

    content = HOOK_RECEIVER_PATH.read_text(encoding="utf-8")

    # Concrete path in _maybe_checkpoint_output: codex exits early and cannot block via hook JSON.
    if "if agent == AgentName.CODEX.value:" in content and "Codex does not support hook blocking" in content:
        blocking["codex"] = False

    return blocking


def _extract_constant_string(node: ast.expr | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def generate_mermaid(
    event_counts: dict[str, int],
    agent_names: list[str],
    adapter_features: dict[str, list[str]],
    protocol_features: dict[str, list[str]],
    checkpoint_blocking: dict[str, bool],
) -> str:
    """Generate Mermaid diagram showing runtime feature matrix."""
    lines: list[str] = [
        "---",
        "title: Runtime Feature Matrix",
        "---",
        "flowchart LR",
    ]

    all_features: set[str] = set()
    for agent in agent_names:
        all_features.update(adapter_features.get(agent, []))
        all_features.update(protocol_features.get(agent, []))
    all_features.add("hook_stop_blocking")

    for agent in agent_names:
        count = event_counts.get(agent, 0)
        hook_label = f"{count} hook events" if count else "no hooks"
        lines.append(f'    {agent}["{agent}<br/>{hook_label}"]')

    lines.append("")

    for feat in sorted(all_features):
        safe_feat = feat.replace(" ", "_")
        lines.append(f"    feat_{safe_feat}({feat})")

    lines.append("")

    for agent in agent_names:
        count = event_counts.get(agent, 0)
        if count:
            lines.append(f"    {agent} --> hooks_{agent}[{count} native events mapped]")

    lines.append("")

    for agent in agent_names:
        for feat in adapter_features.get(agent, []):
            safe_feat = feat.replace(" ", "_")
            lines.append(f"    {agent} --> feat_{safe_feat}")
        for feat in protocol_features.get(agent, []):
            safe_feat = feat.replace(" ", "_")
            lines.append(f"    {agent} --> feat_{safe_feat}")

        if checkpoint_blocking.get(agent, True):
            lines.append(f"    {agent} --> feat_hook_stop_blocking")

    return "\n".join(lines) + "\n"


def main() -> None:
    for path in [EVENTS_PATH, AGENT_TYPES_PATH, CONSTANTS_PATH]:
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            sys.exit(1)

    events_tree = ast.parse(EVENTS_PATH.read_text(encoding="utf-8"), filename=str(EVENTS_PATH))
    agent_tree = ast.parse(AGENT_TYPES_PATH.read_text(encoding="utf-8"), filename=str(AGENT_TYPES_PATH))
    constants_tree = ast.parse(CONSTANTS_PATH.read_text(encoding="utf-8"), filename=str(CONSTANTS_PATH))

    event_counts = parse_hook_event_counts(events_tree)
    agent_names = parse_agent_names(agent_tree) or sorted(event_counts)
    adapter_features = detect_adapter_features(agent_names)
    protocol_features = parse_agent_protocol_features(constants_tree)
    checkpoint_blocking = detect_checkpoint_blocking_features(agent_names)

    if not event_counts:
        print("WARNING: No HOOK_EVENT_MAP entries found", file=sys.stderr)

    mermaid = generate_mermaid(
        event_counts=event_counts,
        agent_names=agent_names,
        adapter_features=adapter_features,
        protocol_features=protocol_features,
        checkpoint_blocking=checkpoint_blocking,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
