#!/usr/bin/env python3
"""Extract state machine diagrams from next_machine/core.py enums and DEFAULT_STATE."""

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = PROJECT_ROOT / "teleclaude" / "core" / "next_machine" / "core.py"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "state-machines.mmd"

# Display labels for roadmap markers (keyed by enum member name)
ROADMAP_LABELS: dict[str, str] = {
    "PENDING": "Pending [ ]",
    "READY": "Ready [.]",
    "IN_PROGRESS": "In Progress [>]",
    "DONE": "Done [x]",
}

# Transitions for roadmap lifecycle
ROADMAP_TRANSITIONS = [
    ("[*]", "PENDING", ""),
    ("PENDING", "READY", "prepare completes"),
    ("READY", "IN_PROGRESS", "work dispatched"),
    ("IN_PROGRESS", "DONE", "finalize completes"),
]

# Transitions for build/review phase
PHASE_TRANSITIONS = [
    ("[*]", "PENDING", ""),
    ("PENDING", "COMPLETE", "build finishes"),
    ("COMPLETE", "APPROVED", "review passes"),
    ("COMPLETE", "CHANGES_REQUESTED", "review requests changes"),
    ("CHANGES_REQUESTED", "PENDING", "fixes applied"),
]


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


def generate_mermaid(
    phase_statuses: list[tuple[str, str]],
    roadmap_markers: list[tuple[str, str]],
) -> str:
    """Generate Mermaid state diagram content from parsed enum members."""
    lines: list[str] = [
        "---",
        "title: Work Item State Machines",
        "---",
        "stateDiagram-v2",
    ]

    # Roadmap lifecycle as composite state
    lines.append('    state "Roadmap Lifecycle" as roadmap {')
    for name, value in roadmap_markers:
        label = ROADMAP_LABELS.get(name, f"{name} [{value}]")
        lines.append(f"        r_{name}: {label}")
    for src, dst, label in ROADMAP_TRANSITIONS:
        prefix_src = f"r_{src}" if not src.startswith("[") else src
        prefix_dst = f"r_{dst}"
        suffix = f": {label}" if label else ""
        lines.append(f"        {prefix_src} --> {prefix_dst}{suffix}")
    lines.append("    }")

    lines.append("")

    # Build/Review phase transitions as composite state
    lines.append('    state "Build/Review Phase" as phase {')
    for name, value in phase_statuses:
        lines.append(f"        p_{name}: {value}")
    for src, dst, label in PHASE_TRANSITIONS:
        prefix_src = f"p_{src}" if not src.startswith("[") else src
        prefix_dst = f"p_{dst}"
        suffix = f": {label}" if label else ""
        lines.append(f"        {prefix_src} --> {prefix_dst}{suffix}")
    lines.append("    }")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not CORE_PATH.exists():
        print(f"ERROR: {CORE_PATH} not found", file=sys.stderr)
        sys.exit(1)

    source = CORE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CORE_PATH))

    phase_statuses = parse_enum_members(tree, "PhaseStatus")
    roadmap_markers = parse_enum_members(tree, "RoadmapMarker")

    if not phase_statuses:
        print("WARNING: No PhaseStatus members found", file=sys.stderr)
    if not roadmap_markers:
        print("WARNING: No RoadmapMarker members found", file=sys.stderr)

    mermaid = generate_mermaid(phase_statuses, roadmap_markers)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
