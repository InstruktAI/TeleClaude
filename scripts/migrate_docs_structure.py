#!/usr/bin/env -S uv run --quiet
"""Migrate documentation structure from agents/docs to docs/global, docs to docs/project."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


class MigrationPlan:
    """Track all changes to be made."""

    def __init__(self) -> None:
        self.file_moves: list[tuple[Path, Path]] = []
        self.dir_creates: list[Path] = []
        self.file_edits: list[tuple[Path, str, str]] = []  # (path, old_content, new_content)
        self.warnings: list[str] = []

    def add_move(self, src: Path, dst: Path) -> None:
        """Record a file/directory move."""
        self.file_moves.append((src, dst))

    def add_dir_create(self, path: Path) -> None:
        """Record a directory creation."""
        self.dir_creates.append(path)

    def add_edit(self, path: Path, old_content: str, new_content: str) -> None:
        """Record a file content edit."""
        if old_content != new_content:
            self.file_edits.append((path, old_content, new_content))

    def add_warning(self, message: str) -> None:
        """Record a warning."""
        self.warnings.append(message)

    def print_report(self) -> None:
        """Print a summary of all planned changes."""
        print("\n" + "=" * 80)
        print("MIGRATION PLAN SUMMARY")
        print("=" * 80)

        if self.dir_creates:
            print(f"\n📁 Directories to create: {len(self.dir_creates)}")
            for path in self.dir_creates:
                print(f"   CREATE: {path}")

        if self.file_moves:
            print(f"\n📦 Files/directories to move: {len(self.file_moves)}")
            for src, dst in self.file_moves[:10]:  # Show first 10
                print(f"   MOVE: {src}")
                print(f"      → {dst}")
            if len(self.file_moves) > 10:
                print(f"   ... and {len(self.file_moves) - 10} more")

        if self.file_edits:
            print(f"\n✏️  Files to edit: {len(self.file_edits)}")
            for path, _, _ in self.file_edits[:10]:  # Show first 10
                print(f"   EDIT: {path}")
            if len(self.file_edits) > 10:
                print(f"   ... and {len(self.file_edits) - 10} more")

        if self.warnings:
            print(f"\n⚠️  Warnings: {len(self.warnings)}")
            for warning in self.warnings:
                print(f"   {warning}")

        print("\n" + "=" * 80)


def check_preconditions(repo_root: Path) -> bool:
    """Verify repository is in expected state."""
    print("Checking preconditions...")

    if not (repo_root / "agents" / "docs").exists():
        print("❌ agents/docs directory not found")
        return False

    if not (repo_root / "docs").exists():
        print("❌ docs directory not found")
        return False

    # Check for existing new structure
    if (repo_root / "docs" / "global").exists():
        print("❌ docs/global already exists - migration may have already run")
        return False

    if (repo_root / "docs" / "project").exists():
        print("❌ docs/project already exists - migration may have already run")
        return False

    print("✅ Preconditions met")
    return True


def plan_directory_moves(repo_root: Path, plan: MigrationPlan) -> None:
    """Plan the directory structure changes."""
    print("\nPlanning directory moves...")

    # Create new structure
    plan.add_dir_create(repo_root / "docs" / "global")
    plan.add_dir_create(repo_root / "docs" / "project")
    plan.add_dir_create(repo_root / "docs" / "third-party")

    # Move agents/docs/* to docs/global/*
    agents_docs = repo_root / "agents" / "docs"
    if agents_docs.exists():
        for item in agents_docs.iterdir():
            src = item
            dst = repo_root / "docs" / "global" / item.name
            plan.add_move(src, dst)

    # Move docs/* to docs/project/* (excluding the new dirs)
    docs_dir = repo_root / "docs"
    if docs_dir.exists():
        for item in docs_dir.iterdir():
            # Skip if it's one of our new directories or other docs-* dirs
            if item.name in ("global", "project", "third-party") or item.name.startswith("docs-"):
                continue
            src = item
            dst = repo_root / "docs" / "project" / item.name
            plan.add_move(src, dst)

    # Move docs-3rd to docs/third-party
    docs_3rd = repo_root / "docs-3rd"
    if docs_3rd.exists():
        for item in docs_3rd.iterdir():
            src = item
            dst = repo_root / "docs" / "third-party" / item.name
            plan.add_move(src, dst)

    print(f"✅ Planned {len(plan.dir_creates)} directory creates, {len(plan.file_moves)} moves")


def update_yaml_index(path: Path, old_prefix: str, new_prefix: str) -> str:
    """Update path fields in YAML index file."""
    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    if not isinstance(data, dict) or "snippets" not in data:
        return content

    modified = False
    for snippet in data["snippets"]:
        if "path" in snippet and snippet["path"].startswith(old_prefix):
            snippet["path"] = snippet["path"].replace(old_prefix, new_prefix, 1)
            modified = True

    if modified:
        return yaml.dump(data, sort_keys=False, allow_unicode=True)
    return content


def plan_yaml_index_updates(repo_root: Path, plan: MigrationPlan) -> None:
    """Plan updates to YAML index files."""
    print("\nPlanning YAML index updates...")

    # agents/docs/index.yaml: path: docs/ → path: docs/global/
    agents_index = repo_root / "agents" / "docs" / "index.yaml"
    if agents_index.exists():
        old_content = agents_index.read_text(encoding="utf-8")
        new_content = update_yaml_index(agents_index, "docs/", "docs/global/")
        plan.add_edit(agents_index, old_content, new_content)

    # docs/index.yaml: path: docs/ → path: docs/project/
    docs_index = repo_root / "docs" / "index.yaml"
    if docs_index.exists():
        old_content = docs_index.read_text(encoding="utf-8")
        new_content = update_yaml_index(docs_index, "docs/", "docs/project/")
        plan.add_edit(docs_index, old_content, new_content)

    print(f"✅ Planned {len(plan.file_edits)} YAML index updates")


def update_markdown_references(content: str, file_path: Path, repo_root: Path) -> str:
    """Update @docs/ and @~/.teleclaude/docs/ references based on file location."""
    rel_path = file_path.relative_to(repo_root)

    if str(rel_path).startswith("docs/global/"):
        # In global docs: @docs/ → @docs/global/ (if not already prefixed)
        content = re.sub(r"@docs/(?!global/|project/|third-party/)", r"@docs/global/", content)
        # Also: @~/.teleclaude/docs/ → @~/.teleclaude/docs/global/
        content = re.sub(
            r"@~/\.teleclaude/docs/(?!global/|project/|third-party/)", r"@~/.teleclaude/docs/global/", content
        )
    elif str(rel_path).startswith("docs/project/"):
        # In project docs: @docs/ → @docs/project/ (if not already prefixed)
        content = re.sub(r"@docs/(?!global/|project/|third-party/)", r"@docs/project/", content)

    return content


def update_markdown_files_after_move(repo_root: Path) -> int:
    """Update markdown file references AFTER files have been moved.

    Returns number of files updated.
    """
    print("\nUpdating markdown references in moved files...")

    count = 0
    for md_file in repo_root.glob("docs/**/*.md"):
        old_content = md_file.read_text(encoding="utf-8")
        new_content = update_markdown_references(old_content, md_file, repo_root)

        if old_content != new_content:
            md_file.write_text(new_content, encoding="utf-8")
            count += 1
            if count <= 5:
                print(f"   Updated: {md_file.relative_to(repo_root)}")

    if count > 5:
        print(f"   ... and {count - 5} more")
    print(f"✅ Updated {count} markdown files")
    return count


def plan_python_updates(repo_root: Path, plan: MigrationPlan) -> None:
    """Plan updates to Python scripts."""
    print("\nPlanning Python script updates...")

    # distribute.py
    distribute_py = repo_root / "scripts" / "distribute.py"
    if distribute_py.exists():
        old_content = distribute_py.read_text(encoding="utf-8")
        new_content = old_content

        # Line 187: master_docs_dir
        new_content = new_content.replace(
            'master_docs_dir = os.path.join(agents_root, "docs")',
            'master_docs_dir = os.path.join(project_root, "docs", "global")',
        )

        # Line 97: docs/ check
        new_content = new_content.replace(
            'if str(candidate).startswith("docs/"):', 'if str(candidate).startswith("docs/project/"):'
        )

        # Line 150-151: YAML path fix
        new_content = new_content.replace('if "path: agents/docs/" in line:', 'if "path: docs/global/" in line:')
        new_content = new_content.replace(
            'line.replace("path: agents/docs/", "path: docs/")',
            'line.replace("path: docs/global/", "path: docs/project/")',
        )

        plan.add_edit(distribute_py, old_content, new_content)

    # gitattributes.py
    gitattributes_py = repo_root / "teleclaude" / "project_setup" / "gitattributes.py"
    if gitattributes_py.exists():
        old_content = gitattributes_py.read_text(encoding="utf-8")
        new_content = old_content.replace(
            '"docs/**/*.md filter=teleclaude-docs",\n    "agents/docs/**/*.md filter=teleclaude-docs",',
            '"docs/project/**/*.md filter=teleclaude-docs",\n    "docs/global/**/*.md filter=teleclaude-docs",',
        )
        plan.add_edit(gitattributes_py, old_content, new_content)

    print(f"✅ Planned {len([e for e in plan.file_edits if e[0].suffix == '.py'])} Python file updates")


def plan_gitattributes_update(repo_root: Path, plan: MigrationPlan) -> None:
    """Plan update to .gitattributes file."""
    print("\nPlanning .gitattributes update...")

    gitattributes = repo_root / ".gitattributes"
    if gitattributes.exists():
        old_content = gitattributes.read_text(encoding="utf-8")
        new_content = old_content.replace(
            "docs/**/*.md filter=teleclaude-docs", "docs/project/**/*.md filter=teleclaude-docs"
        ).replace("agents/docs/**/*.md filter=teleclaude-docs", "docs/global/**/*.md filter=teleclaude-docs")
        plan.add_edit(gitattributes, old_content, new_content)
        print("✅ Planned .gitattributes update")


def execute_plan(plan: MigrationPlan, repo_root: Path, dry_run: bool) -> bool:
    """Execute the migration plan."""
    if dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made")
        return True

    print("\n🚀 Executing migration plan...")

    # 1. Create directories
    for dir_path in plan.dir_creates:
        print(f"Creating directory: {dir_path}")
        dir_path.mkdir(parents=True, exist_ok=True)

    # 2. Execute file moves
    for src, dst in plan.file_moves:
        print(f"Moving: {src.name}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

    # 3. Execute YAML and Python file edits (before markdown updates)
    for path, _, new_content in plan.file_edits:
        print(f"Updating: {path}")
        path.write_text(new_content, encoding="utf-8")

    # 4. Update markdown references in moved files
    update_markdown_files_after_move(repo_root)

    # 5. Clean up empty directories
    old_dirs = [
        repo_root / "agents" / "docs",
        repo_root / "docs-3rd",
    ]
    for old_dir in old_dirs:
        if old_dir.exists() and not list(old_dir.iterdir()):
            print(f"Removing empty directory: {old_dir}")
            old_dir.rmdir()

    print("✅ Migration complete")
    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Migrate documentation structure")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory",
    )
    args = parser.parse_args()

    repo_root: Path = args.repo_root.resolve()

    print(f"Repository root: {repo_root}")

    if not check_preconditions(repo_root):
        return 1

    # Build migration plan
    plan = MigrationPlan()

    plan_directory_moves(repo_root, plan)
    plan_yaml_index_updates(repo_root, plan)
    plan_python_updates(repo_root, plan)
    plan_gitattributes_update(repo_root, plan)

    # Note: Markdown files will be updated AFTER moves in execute_plan
    plan.add_warning("Markdown @docs/ references will be updated after files are moved")

    # Show the plan
    plan.print_report()

    if not args.dry_run:
        response = input("\n⚠️  Execute this migration? (yes/no): ")
        if response.lower() != "yes":
            print("Migration cancelled")
            return 0

    # Execute
    success = execute_plan(plan, repo_root, args.dry_run)

    if success and not args.dry_run:
        print("\n" + "=" * 80)
        print("NEXT STEPS:")
        print("=" * 80)
        print("1. Run: uv run scripts/build_snippet_index.py")
        print("2. Run: uv run scripts/distribute.py --deploy")
        print("3. Run: git status (verify changes)")
        print("4. Run tests: uv run pytest")
        print("5. Verify MCP context retrieval works")
        print("=" * 80)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
