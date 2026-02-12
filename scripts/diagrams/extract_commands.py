#!/usr/bin/env python3
"""Extract command dispatch diagram from command frontmatter and next_machine dispatch sites."""

import ast
import re
import sys
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_DIR = PROJECT_ROOT / "agents" / "commands"
NEXT_MACHINE_CORE_PATH = PROJECT_ROOT / "teleclaude" / "core" / "next_machine" / "core.py"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "command-dispatch.mmd"

COMMAND_ROLES: dict[str, str] = {
    "next-prepare": "router",
    "next-prepare-draft": "worker",
    "next-prepare-gate": "worker",
    "next-work": "orchestrator",
    "next-build": "worker",
    "next-review": "worker",
    "next-fix-review": "worker",
    "next-defer": "orchestrator",
    "next-finalize": "worker",
    "next-maintain": "worker",
    "next-research": "worker",
    "prime-orchestrator": "orchestrator",
}


def parse_command_frontmatter(path: Path) -> dict[str, str]:
    """Parse YAML frontmatter from a command markdown file."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        return {}

    end_idx = content.find("\n---", 4)
    if end_idx == -1:
        return {}

    frontmatter_text = content[4:end_idx]
    frontmatter: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        frontmatter[key.strip()] = raw_value.strip().strip("'\"")

    return frontmatter


def parse_all_commands() -> list[dict[str, str]]:
    """Parse all command files and return metadata."""
    commands: list[dict[str, str]] = []

    for md_file in sorted(COMMANDS_DIR.glob("*.md")):
        frontmatter = parse_command_frontmatter(md_file)
        commands.append(
            {
                "name": md_file.stem,
                "description": frontmatter.get("description", ""),
                "argument_hint": frontmatter.get("argument-hint", ""),
            }
        )

    return commands


def parse_dispatch_edges(tree: ast.Module) -> list[tuple[str, str, str]]:
    """Extract dispatch edges from next_machine format_tool_call usage.

    Returns (src_command, dst_command, label).
    """
    edges: list[tuple[str, str, str]] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("next_"):
            continue

        src_command = node.name.replace("_", "-")
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if not isinstance(call.func, ast.Name) or call.func.id != "format_tool_call":
                continue

            command_value = _extract_keyword_str(call, "command")
            if not command_value:
                continue

            edges.append((src_command, command_value, "dispatch"))

    return _dedupe_edges(edges)


def _extract_keyword_str(call: ast.Call, keyword_name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg != keyword_name:
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
        if isinstance(keyword.value, ast.JoinedStr):
            parts: list[str] = []
            for value in keyword.value.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append("{expr}")
            return "".join(parts)
    return None


def parse_post_completion_next_calls(tree: ast.Module) -> list[tuple[str, str, str]]:
    """Extract command-to-command re-entry edges from format_tool_call next_call values."""
    edges: list[tuple[str, str, str]] = []
    tool_call_re: re.Pattern[str] = re.compile(r"teleclaude__([a-z_]+)")

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("next_"):
            continue

        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if not isinstance(call.func, ast.Name) or call.func.id != "format_tool_call":
                continue

            command_value = _extract_keyword_str(call, "command")
            if not command_value:
                continue

            next_call_value = _extract_keyword_str(call, "next_call")
            if not next_call_value:
                continue

            found = cast(list[str], tool_call_re.findall(next_call_value))
            for tool_name in found:
                dst_command = tool_name.replace("_", "-")
                if dst_command.startswith("next-"):
                    edges.append((command_value, dst_command, "post-completion"))

    return _dedupe_edges(edges)


def _dedupe_edges(edges: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    deduped: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        if edge not in seen:
            seen.add(edge)
            deduped.append(edge)
    return deduped


def generate_mermaid(
    commands: list[dict[str, str]],
    dispatch_edges: list[tuple[str, str, str]],
    post_completion_edges: list[tuple[str, str, str]],
) -> str:
    """Generate Mermaid flowchart showing extracted command dispatch edges."""
    lines: list[str] = [
        "---",
        "title: Command Dispatch",
        "---",
        "flowchart TD",
    ]

    command_names = {command["name"] for command in commands}

    for command in commands:
        name = command["name"]
        safe_name = name.replace("-", "_")
        description = command["description"]
        role = COMMAND_ROLES.get(name, "worker")

        if role in {"orchestrator", "router"}:
            lines.append(f'    {safe_name}{{{{"{name}<br/>{description}"}}}}')
        else:
            lines.append(f'    {safe_name}["{name}<br/>{description}"]')

    lines.append("")

    for src, dst, label in dispatch_edges + post_completion_edges:
        if src not in command_names or dst not in command_names:
            continue
        lines.append(f"    {src.replace('-', '_')} -->|{label}| {dst.replace('-', '_')}")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not COMMANDS_DIR.exists():
        print(f"ERROR: {COMMANDS_DIR} not found", file=sys.stderr)
        sys.exit(1)
    if not NEXT_MACHINE_CORE_PATH.exists():
        print(f"ERROR: {NEXT_MACHINE_CORE_PATH} not found", file=sys.stderr)
        sys.exit(1)

    commands = parse_all_commands()
    source = NEXT_MACHINE_CORE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(NEXT_MACHINE_CORE_PATH))

    dispatch_edges = parse_dispatch_edges(tree)
    post_completion_edges = parse_post_completion_next_calls(tree)

    if not commands:
        print("WARNING: No command files found", file=sys.stderr)

    mermaid = generate_mermaid(commands, dispatch_edges, post_completion_edges)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
