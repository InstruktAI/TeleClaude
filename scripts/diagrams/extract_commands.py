#!/usr/bin/env python3
"""Extract command dispatch diagram from agents/commands/ markdown frontmatter."""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMMANDS_DIR = PROJECT_ROOT / "agents" / "commands"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "command-dispatch.mmd"

# Known orchestration flow order
ORCHESTRATION_ORDER = [
    "next-prepare",
    "next-prepare-draft",
    "next-prepare-gate",
    "next-work",
    "next-build",
    "next-review",
    "next-fix-review",
    "next-defer",
    "next-finalize",
    "next-maintain",
]

# Semantic grouping for node shapes
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
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}

    frontmatter: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip().strip("'\"")

    return frontmatter


def parse_all_commands() -> list[dict[str, str]]:
    """Parse all command files and return their metadata."""
    commands: list[dict[str, str]] = []

    for md_file in sorted(COMMANDS_DIR.glob("*.md")):
        fm = parse_command_frontmatter(md_file)
        name = md_file.stem
        commands.append(
            {
                "name": name,
                "description": fm.get("description", ""),
                "argument_hint": fm.get("argument-hint", ""),
            }
        )

    return commands


def generate_mermaid(commands: list[dict[str, str]]) -> str:
    """Generate Mermaid flowchart showing command orchestration."""
    lines: list[str] = [
        "---",
        "title: Command Dispatch",
        "---",
        "flowchart TD",
    ]

    # Create nodes for known orchestration commands
    cmd_names = {c["name"] for c in commands}

    for cmd in commands:
        name = cmd["name"]
        safe_name = name.replace("-", "_")
        desc = cmd["description"]
        role = COMMAND_ROLES.get(name, "worker")

        # Shape by role
        if role == "orchestrator":
            lines.append(f'    {safe_name}{{{{"{name}<br/>{desc}"}}}}')
        elif role == "router":
            lines.append(f'    {safe_name}{{{{"{name}<br/>{desc}"}}}}')
        else:
            lines.append(f'    {safe_name}["{name}<br/>{desc}"]')

    lines.append("")

    # Draw orchestration flow edges
    flow_edges = [
        ("next-prepare", "next-prepare-draft", "draft"),
        ("next-prepare", "next-prepare-gate", "gate"),
        ("next-prepare-gate", "next-work", "ready"),
        ("next-work", "next-build", "build phase"),
        ("next-work", "next-review", "review phase"),
        ("next-review", "next-fix-review", "changes requested"),
        ("next-fix-review", "next-review", "re-review"),
        ("next-work", "next-defer", "deferrals pending"),
        ("next-work", "next-finalize", "approved"),
    ]

    for src, dst, label in flow_edges:
        if src in cmd_names and dst in cmd_names:
            safe_src = src.replace("-", "_")
            safe_dst = dst.replace("-", "_")
            lines.append(f"    {safe_src} -->|{label}| {safe_dst}")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not COMMANDS_DIR.exists():
        print(f"ERROR: {COMMANDS_DIR} not found", file=sys.stderr)
        sys.exit(1)

    commands = parse_all_commands()
    if not commands:
        print("WARNING: No command files found", file=sys.stderr)

    mermaid = generate_mermaid(commands)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
