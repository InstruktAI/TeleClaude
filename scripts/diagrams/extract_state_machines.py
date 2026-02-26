#!/usr/bin/env python3
"""Extract state machine diagrams from next_machine/core.py without hardcoded transitions."""

import ast
import re
import sys
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = PROJECT_ROOT / "teleclaude" / "core" / "next_machine" / "core.py"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "state-machines.mmd"


def parse_enum_members(tree: ast.Module, class_name: str) -> list[tuple[str, str]]:
    """Extract (name, value) pairs from a str Enum class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            members: list[tuple[str, str]] = []
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and isinstance(item.value, ast.Constant):
                            members.append((target.id, str(item.value.value)))
            return members
    return []


def parse_default_phase_state(tree: ast.Module) -> dict[str, str]:
    """Extract DEFAULT_STATE phase defaults as {phase: status}."""
    defaults: dict[str, str] = {}

    for node in ast.walk(tree):
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "DEFAULT_STATE":
            value = node.value
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "DEFAULT_STATE" for target in node.targets):
                value = node.value
        if not isinstance(value, ast.Dict):
            continue

        for key_node, value_node in zip(value.keys, value.values):
            phase = _extract_enum_value_name(key_node, "PhaseName")
            status = _extract_enum_value_name(value_node, "PhaseStatus")
            if phase and status:
                defaults[phase.lower()] = status.lower()

    return defaults


def _extract_enum_value_name(node: ast.expr | None, enum_name: str) -> str | None:
    if not isinstance(node, ast.Attribute):
        return None
    if node.attr != "value":
        return None
    enum_member = node.value
    if not isinstance(enum_member, ast.Attribute):
        return None
    if not isinstance(enum_member.value, ast.Name) or enum_member.value.id != enum_name:
        return None
    return enum_member.attr


def parse_post_completion_text(tree: ast.Module) -> dict[str, str]:
    """Extract POST_COMPLETION command bodies as {command: text}."""
    result: dict[str, str] = {}

    for node in ast.walk(tree):
        value: ast.expr | None = None
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "POST_COMPLETION"
        ):
            value = node.value
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "POST_COMPLETION" for target in node.targets):
                value = node.value
        if not isinstance(value, ast.Dict):
            continue

        for key_node, value_node in zip(value.keys, value.values):
            if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
                continue
            if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                result[key_node.value] = value_node.value

    return result


def parse_phase_transitions(
    defaults: dict[str, str],
    post_completion: dict[str, str],
) -> list[tuple[str, str, str]]:
    """Derive phase transitions from POST_COMPLETION mark_phase instructions."""
    status_updates: dict[str, list[tuple[str, str]]] = {}
    legacy_re: re.Pattern[str] = re.compile(
        r'telec todo mark-phase\(slug="\{args\}", phase="([a-z]+)", status="([a-z_]+)"\)'
    )
    cli_re: re.Pattern[str] = re.compile(r"telec todo mark-phase \{args\} --phase ([a-z]+) --status ([a-z_]+)")

    for command, body in post_completion.items():
        legacy_matches = cast(list[tuple[str, str]], legacy_re.findall(body))
        cli_matches = cast(list[tuple[str, str]], cli_re.findall(body))
        for phase, status in [*legacy_matches, *cli_matches]:
            status_updates.setdefault(phase, []).append((status, command))

    transitions: list[tuple[str, str, str]] = []

    for phase, updates in status_updates.items():
        default_status = defaults.get(phase, "pending")
        statuses = {status for status, _ in updates}

        for status, command in updates:
            if status != default_status:
                transitions.append((default_status, status, command))

        # If a command moves the phase back to default, connect non-default -> default.
        default_commands = [command for status, command in updates if status == default_status]
        if default_commands:
            back_command = default_commands[0]
            for status in sorted(statuses):
                if status != default_status:
                    transitions.append((status, default_status, back_command))

    # Deduplicate while preserving order
    deduped: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for transition in transitions:
        if transition not in seen:
            seen.add(transition)
            deduped.append(transition)

    return deduped


def generate_mermaid(
    phase_statuses: list[tuple[str, str]],
    phase_transitions: list[tuple[str, str, str]],
) -> str:
    """Generate Mermaid state diagram from parsed enums and extracted transitions."""
    lines: list[str] = [
        "---",
        "title: Work Item Phase State Machine",
        "---",
        "stateDiagram-v2",
    ]

    lines.append('    state "Build/Review Phase" as phase {')
    status_name_to_value = {name.lower(): value for name, value in phase_statuses}
    for name, value in phase_statuses:
        lines.append(f"        p_{name}: {value}")

    if any(name == "PENDING" for name, _ in phase_statuses):
        lines.append("        [*] --> p_PENDING")

    for src, dst, label in phase_transitions:
        src_name = src.upper()
        dst_name = dst.upper()
        if src in status_name_to_value and dst in status_name_to_value:
            lines.append(f"        p_{src_name} --> p_{dst_name}: {label}")
    lines.append("    }")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not CORE_PATH.exists():
        print(f"ERROR: {CORE_PATH} not found", file=sys.stderr)
        sys.exit(1)

    source = CORE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CORE_PATH))

    phase_statuses = parse_enum_members(tree, "PhaseStatus")
    defaults = parse_default_phase_state(tree)
    post_completion = parse_post_completion_text(tree)

    phase_transitions = parse_phase_transitions(defaults, post_completion)

    if not phase_statuses:
        print("WARNING: No PhaseStatus members found", file=sys.stderr)

    mermaid = generate_mermaid(
        phase_statuses=phase_statuses,
        phase_transitions=phase_transitions,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
