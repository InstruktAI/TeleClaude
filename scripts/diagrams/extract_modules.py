#!/usr/bin/env python3
"""Extract module dependency graph from import statements across teleclaude/."""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TELECLAUDE_PATH = PROJECT_ROOT / "teleclaude"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "diagrams" / "module-layers.mmd"

# Top-level packages within teleclaude/ to track
KNOWN_PACKAGES = {
    "core",
    "hooks",
    "mcp",
    "cli",
    "adapters",
    "transport",
    "memory",
    "cron",
    "helpers",
    "utils",
    "config",
    "services",
    "tts",
    "stt",
    "tools",
    "types",
    "entrypoints",
    "runtime",
    "install",
    "project_setup",
    "tagging",
}

IMPORT_RE = re.compile(r"^\s*import\s+(.+)$", re.MULTILINE)
FROM_RE = re.compile(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\b", re.MULTILINE)


def extract_package_deps() -> dict[str, set[str]]:
    """Walk teleclaude/ and extract inter-package dependencies."""
    deps: dict[str, set[str]] = {pkg: set() for pkg in KNOWN_PACKAGES}

    for py_file in TELECLAUDE_PATH.rglob("*.py"):
        # Determine which package this file belongs to
        relative = py_file.relative_to(TELECLAUDE_PATH)
        parts = relative.parts
        if len(parts) < 1:
            continue
        # First directory component is the package
        source_pkg = parts[0] if len(parts) > 1 else "__root__"
        if source_pkg not in KNOWN_PACKAGES:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for line in source.splitlines():
            for target_pkg in _resolve_import_line(line):
                if target_pkg != source_pkg and target_pkg in KNOWN_PACKAGES:
                    deps[source_pkg].add(target_pkg)

    return deps


def _resolve_import_line(line: str) -> set[str]:
    """Resolve one import statement line to teleclaude packages, if present."""
    targets: set[str] = set()

    import_match = IMPORT_RE.match(line)
    if import_match:
        imports = import_match.group(1)
        for candidate in imports.split(","):
            module_path = candidate.strip().split(" as ", 1)[0].strip()
            target_pkg = _resolve_teleclaude_package(module_path)
            if target_pkg:
                targets.add(target_pkg)
        return targets

    from_match = FROM_RE.match(line)
    if from_match:
        target_pkg = _resolve_teleclaude_package(from_match.group(1).strip())
        if target_pkg:
            targets.add(target_pkg)

    return targets


def _resolve_teleclaude_package(module_path: str) -> str | None:
    """Extract the teleclaude sub-package from a dotted module path."""
    parts = module_path.split(".")
    if len(parts) >= 2 and parts[0] == "teleclaude":
        return parts[1]
    return None


def generate_mermaid(deps: dict[str, set[str]]) -> str:
    """Generate Mermaid flowchart from package dependencies."""
    lines: list[str] = [
        "---",
        "title: Module Dependency Graph (package level)",
        "---",
        "flowchart TD",
    ]

    # Only include packages that have dependencies or are depended upon
    active_pkgs: set[str] = set()
    for src, targets in deps.items():
        if targets:
            active_pkgs.add(src)
            active_pkgs.update(targets)

    for pkg in sorted(active_pkgs):
        lines.append(f"    {pkg}[{pkg}]")

    lines.append("")

    for src in sorted(deps):
        for dst in sorted(deps[src]):
            lines.append(f"    {src} --> {dst}")

    return "\n".join(lines) + "\n"


def main() -> None:
    if not TELECLAUDE_PATH.exists():
        print(f"ERROR: {TELECLAUDE_PATH} not found", file=sys.stderr)
        sys.exit(1)

    deps = extract_package_deps()

    # Filter out empty entries
    deps = {k: v for k, v in deps.items() if v}

    if not deps:
        print("WARNING: No inter-package dependencies found", file=sys.stderr)

    mermaid = generate_mermaid(deps)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
