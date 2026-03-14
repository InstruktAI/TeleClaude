"""Handlers for telec todo demo subcommands."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from teleclaude.cli.telec.help import _usage

__all__ = [
    "_check_no_demo_marker",
    "_demo_create",
    "_demo_list",
    "_demo_run",
    "_demo_validate",
    "_extract_demo_blocks",
    "_find_demo_md",
    "_handle_todo_demo",
]


def _extract_demo_blocks(content: str) -> list[tuple[int, str, bool, str]]:
    """Extract bash blocks from demo.md with skip-validation metadata.

    Returns tuples of (line_number, block_text, skipped, skip_reason).
    """

    blocks: list[tuple[int, str, bool, str]] = []
    skip_pattern = re.compile(r"<!--\s*skip-validation:\s*(.+?)\s*-->")
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        skip_match = skip_pattern.search(line)
        if skip_match:
            skip_reason = skip_match.group(1)
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("```bash"):
                block_start = j + 1
                block_lines: list[str] = []
                k = block_start
                while k < len(lines) and lines[k].strip() != "```":
                    block_lines.append(lines[k])
                    k += 1
                blocks.append((j + 1, "\n".join(block_lines), True, skip_reason))
                i = k + 1
                continue
            i += 1
            continue

        if line.strip().startswith("```bash"):
            block_start = i + 1
            block_lines: list[str] = []
            k = block_start
            while k < len(lines) and lines[k].strip() != "```":
                block_lines.append(lines[k])
                k += 1
            blocks.append((i + 1, "\n".join(block_lines), False, ""))
            i = k + 1
            continue

        i += 1

    return blocks


def _find_demo_md(slug: str, project_root: Path) -> Path | None:
    """Find demo.md for a slug. Searches todos/ first, then demos/."""
    for candidate in [
        project_root / "todos" / slug / "demo.md",
        project_root / "demos" / slug / "demo.md",
    ]:
        if candidate.exists():
            return candidate
    return None


def _check_no_demo_marker(content: str) -> str | None:
    """Check for <!-- no-demo: reason --> marker in first 10 lines.

    Returns reason string if found, None otherwise.
    """

    pattern = re.compile(r"<!--\s*no-demo:\s*(.+?)\s*-->")
    for line in content.split("\n")[:10]:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


def _demo_list(project_root: Path) -> None:
    """List available demos from demos/ directory."""
    import json

    demos_dir = project_root / "demos"
    if not demos_dir.exists():
        print("No demos available")
        raise SystemExit(0)

    demo_entries = []
    missing_snapshot: list[str] = []
    broken_snapshot: list[str] = []
    for demo_path in sorted(demos_dir.iterdir()):
        if not demo_path.is_dir() or demo_path.name.startswith("."):
            continue
        snapshot_path = demo_path / "snapshot.json"
        if not snapshot_path.exists():
            missing_snapshot.append(demo_path.name)
            continue
        try:
            snapshot = json.loads(snapshot_path.read_text())
            demo_entries.append((demo_path.name, snapshot))
        except (json.JSONDecodeError, OSError):
            broken_snapshot.append(demo_path.name)

    if not demo_entries and not missing_snapshot and not broken_snapshot:
        print("No demos available")
        raise SystemExit(0)

    if demo_entries:
        print(f"Available demos ({len(demo_entries)}):\n")
        print(f"{'Slug':<30} {'Title':<50} {'Version':<10} {'Delivered'}")
        print("-" * 110)
        for demo_slug, snapshot in demo_entries:
            title = snapshot.get("title", "")
            version = snapshot.get("version", "")
            delivered = snapshot.get("delivered_date", snapshot.get("delivered", ""))
            print(f"{demo_slug:<30} {title:<50} {version:<10} {delivered}")

    if missing_snapshot:
        print(f"\nMissing snapshot.json ({len(missing_snapshot)}):")
        for slug in missing_snapshot:
            print(f"  {slug}")
        print("  Run: telec todo demo create <slug>")

    if broken_snapshot:
        print(f"\nBroken snapshot.json ({len(broken_snapshot)}):")
        for slug in broken_snapshot:
            print(f"  {slug}")

    raise SystemExit(0)


def _demo_validate(slug: str, project_root: Path) -> None:
    """Structural validation of demo.md — checks blocks exist and content diverges from skeleton."""
    demo_md_path = _find_demo_md(slug, project_root)
    if demo_md_path is None:
        print(f"Error: No demo.md found for '{slug}'")
        raise SystemExit(1)

    print(f"Validating demo: {slug}")
    print(f"Source: {demo_md_path.relative_to(project_root)}\n")

    content = demo_md_path.read_text(encoding="utf-8")

    # Check for no-demo escape hatch — emit warning so build gate and reviewer can't miss it
    no_demo_reason = _check_no_demo_marker(content)
    if no_demo_reason is not None:
        print(f"WARNING: no-demo marker found: {no_demo_reason}")
        print(
            "Reviewer must verify justification — only pure internal refactors with zero user-visible change qualify."
        )
        raise SystemExit(0)

    # Check that demo.md diverges from the skeleton template.
    # Strip the {slug} placeholder before comparing so a scaffolded-but-unmodified
    # demo.md is caught regardless of the actual slug value.
    skeleton_path = project_root / "templates" / "todos" / "demo.md"
    if skeleton_path.exists():
        skeleton = skeleton_path.read_text(encoding="utf-8").replace("{slug}", slug)
        if content.strip() == skeleton.strip():
            print("Validation failed: demo.md is unchanged from the skeleton template — no demo implemented")
            raise SystemExit(1)

    blocks = _extract_demo_blocks(content)
    executable = [b for b in blocks if not b[2]]

    if not executable:
        print("Validation failed: no executable bash blocks found")
        raise SystemExit(1)

    print(f"Validation passed: {len(executable)} executable block(s) found")
    if len(blocks) > len(executable):
        print(f"Skipped: {len(blocks) - len(executable)} block(s)")
    raise SystemExit(0)


def _demo_run(slug: str, project_root: Path) -> None:
    """Execute bash blocks from demo.md."""
    demo_md_path = _find_demo_md(slug, project_root)

    if demo_md_path is not None:
        print(f"Running demo: {slug}\n")
        print(f"Source: {demo_md_path.relative_to(project_root)}\n")

        content = demo_md_path.read_text(encoding="utf-8")

        # Check for no-demo escape hatch
        no_demo_reason = _check_no_demo_marker(content)
        if no_demo_reason is not None:
            print(f"WARNING: no-demo marker found: {no_demo_reason}")
            raise SystemExit(0)

        blocks = _extract_demo_blocks(content)

        if not blocks:
            print("Error: no executable blocks found in demo.md")
            raise SystemExit(1)

        executable = [(ln, blk, reason) for ln, blk, skipped, reason in blocks if not skipped]
        skipped = [(ln, blk, reason) for ln, blk, skipped, reason in blocks if skipped]

        if skipped:
            for ln, _blk, reason in skipped:
                print(f"  SKIP  block at line {ln}: {reason}")
            print()

        if not executable:
            print("Error: all code blocks skipped, no executable blocks")
            raise SystemExit(1)

        # Prepend project venv to PATH so demo blocks use the correct Python
        env = os.environ.copy()
        venv_bin = project_root / ".venv" / "bin"
        if venv_bin.is_dir():
            env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = str(project_root / ".venv")

        passed = 0
        for ln, block, _reason in executable:
            preview = block.strip().split("\n")[0][:60]
            print(f"  RUN   block at line {ln}: {preview}")
            result = subprocess.run(block, shell=True, cwd=project_root, env=env)
            if result.returncode != 0:
                print(f"  FAIL  block at line {ln} exited with {result.returncode}")
                raise SystemExit(1)
            print(f"  PASS  block at line {ln}")
            passed += 1

        print(f"\nDemo passed: {passed}/{len(executable)} blocks")
        if skipped:
            print(f"Skipped: {len(skipped)} blocks")
        raise SystemExit(0)

    # Fallback: snapshot.json demo field (backward compatibility)
    import json

    pyproject_path = project_root / "pyproject.toml"
    current_version = "0.0.0"
    if pyproject_path.exists():
        pyproject_content = pyproject_path.read_text()
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject_content)
        if match:
            current_version = match.group(1)
    current_major = int(current_version.split(".")[0])

    demos_dir = project_root / "demos"
    demo_path = demos_dir / slug
    snapshot_path = demo_path / "snapshot.json"

    if not demo_path.exists() or not snapshot_path.exists():
        print(f"Error: Demo '{slug}' not found")
        raise SystemExit(1)

    try:
        snapshot = json.loads(snapshot_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error reading snapshot for '{slug}': {exc}")
        raise SystemExit(1) from exc

    demo_version = snapshot.get("version", "0.0.0")
    demo_major = int(demo_version.split(".")[0])

    if demo_major != current_major:
        print(
            f"Demo from v{demo_version} is incompatible with current v{current_version} "
            f"(major version mismatch). Skipping."
        )
        raise SystemExit(0)

    demo_command = snapshot.get("demo")
    if not demo_command:
        print(f"Warning: Demo '{slug}' has no demo.md or 'demo' field. Skipping execution.")
        raise SystemExit(0)

    print(f"Running demo: {slug} (v{demo_version})\n")
    result = subprocess.run(demo_command, shell=True, cwd=demo_path)
    raise SystemExit(result.returncode)


def _demo_create(slug: str, project_root: Path) -> None:
    """Promote demo.md to demos/{slug}/ with minimal snapshot.json."""
    import json

    source = _find_demo_md(slug, project_root)
    if source is None:
        print(f"Error: No demo.md found for '{slug}'")
        raise SystemExit(1)

    # Read title from demo.md H1
    content = source.read_text(encoding="utf-8")
    title = slug
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            # Strip "Demo: " prefix if present
            if title.lower().startswith("demo:"):
                title = title[5:].strip()
            break

    # Read version from pyproject.toml
    pyproject_path = project_root / "pyproject.toml"
    version = "0.0.0"
    if pyproject_path.exists():
        pyproject_content = pyproject_path.read_text()
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject_content)
        if match:
            version = match.group(1)

    # Create demos/{slug}/ and copy demo.md (skip if already in place)
    demos_dir = project_root / "demos" / slug
    demos_dir.mkdir(parents=True, exist_ok=True)
    dest = demos_dir / "demo.md"
    if source.resolve() != dest.resolve():
        import shutil

        shutil.copy2(source, dest)

    # Generate minimal snapshot.json
    snapshot = {"slug": slug, "title": title, "version": version}
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")

    print(f"Demo promoted: {source.relative_to(project_root)} -> demos/{slug}/")
    print(f"Snapshot: {json.dumps(snapshot)}")
    raise SystemExit(0)


def _handle_todo_demo(args: list[str]) -> None:
    """Handle telec todo demo subcommands: list, validate, run, create."""
    _DEMO_SUBCOMMANDS = {"list", "validate", "run", "create"}
    # Backward compatibility:
    # - `telec todo demo` lists demos
    # - `telec todo demo <slug>` runs demo for slug
    project_root = Path.cwd()
    if not args:
        subcommand = "list"
        remaining_args: list[str] = []
    else:
        subcommand = args[0]
        remaining_args = args[1:]
    slug: str | None = None

    # Backward compatibility: `telec todo demo <slug>` behaves like
    # `telec todo demo run <slug>`.
    if subcommand not in _DEMO_SUBCOMMANDS:
        if subcommand.startswith("-"):
            print(f"Unknown option: {subcommand}")
            print(_usage("todo", "demo"))
            raise SystemExit(1)
        slug = subcommand
        subcommand = "run"

    i = 0
    while i < len(remaining_args):
        arg = remaining_args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "demo"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "demo"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if subcommand == "list":
        if slug is not None:
            print("The 'list' subcommand does not take a slug.")
            print(_usage("todo", "demo"))
            raise SystemExit(1)
        _demo_list(project_root)
        return

    # validate/run/create require slug
    if slug is None:
        print(f"Missing required slug for 'demo {subcommand}'.")
        print(_usage("todo", "demo"))
        raise SystemExit(1)

    if subcommand == "validate":
        _demo_validate(slug, project_root)
    elif subcommand == "run":
        _demo_run(slug, project_root)
    elif subcommand == "create":
        _demo_create(slug, project_root)
