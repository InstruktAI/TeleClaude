"""Pre-commit hook installation for TeleClaude docs check."""

from pathlib import Path

# Check command that detects hardcoded HOME paths in staged .md files
PRECOMMIT_CHECK = (
    "git diff --cached --name-only --diff-filter=ACM | "
    "grep '\\.md$' | "
    'xargs -r grep -l "@/Users/\\|@/home/" && '
    "echo \"ERROR: Hardcoded HOME paths found in docs. Run 'telec init' to set up filters.\" && "
    "exit 1 || true"
)


def install_precommit_hook(project_root: Path) -> None:
    """Install pre-commit hook to catch hardcoded HOME paths.

    Detects the hook system in use (pre-commit framework, Husky, or raw git hooks)
    and adds the check appropriately.

    Args:
        project_root: Path to the project root directory.
    """
    precommit_config = project_root / ".pre-commit-config.yaml"
    husky_dir = project_root / ".husky"
    git_hooks_dir = project_root / ".git" / "hooks"

    if precommit_config.exists():
        _add_precommit_framework_hook(precommit_config)
    elif husky_dir.exists():
        _add_husky_hook(husky_dir)
    elif git_hooks_dir.exists():
        _add_raw_git_hook(git_hooks_dir)
    else:
        print("telec init: no git hooks directory found, skipping hook installation.")


def _add_precommit_framework_hook(config_path: Path) -> None:
    """Add hook to pre-commit framework config."""
    import yaml

    content = config_path.read_text(encoding="utf-8")

    if "teleclaude-docs-check" in content:
        print("telec init: pre-commit hook already configured.")
        return

    try:
        config = yaml.safe_load(content) or {}
    except Exception:
        print("telec init: failed to parse .pre-commit-config.yaml, skipping hook.")
        return

    if "repos" not in config:
        config["repos"] = []

    teleclaude_hook = {
        "repo": "local",
        "hooks": [
            {
                "id": "teleclaude-docs-check",
                "name": "Check for hardcoded HOME paths in docs",
                "entry": "bash -c",
                "args": [PRECOMMIT_CHECK],
                "language": "system",
                "files": r"\.md$",
                "pass_filenames": False,
            }
        ],
    }
    config["repos"].append(teleclaude_hook)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
    print("telec init: pre-commit hook added to .pre-commit-config.yaml.")


def _add_husky_hook(husky_dir: Path) -> None:
    """Add check to Husky pre-commit hook."""
    hook_file = husky_dir / "pre-commit"

    existing_content = ""
    if hook_file.exists():
        existing_content = hook_file.read_text(encoding="utf-8")
        if "teleclaude-docs-check" in existing_content:
            print("telec init: husky hook already configured.")
            return

    check_block = f"""
# teleclaude-docs-check: Reject hardcoded HOME paths
{PRECOMMIT_CHECK}
"""

    with open(hook_file, "a", encoding="utf-8") as f:
        if existing_content and not existing_content.endswith("\n"):
            f.write("\n")
        f.write(check_block)

    hook_file.chmod(hook_file.stat().st_mode | 0o111)
    print("telec init: husky pre-commit hook updated.")


def _add_raw_git_hook(hooks_dir: Path) -> None:
    """Add or create raw git pre-commit hook."""
    hook_file = hooks_dir / "pre-commit"

    existing_content = ""
    if hook_file.exists():
        existing_content = hook_file.read_text(encoding="utf-8")
        if "teleclaude-docs-check" in existing_content:
            print("telec init: git hook already configured.")
            return

    if not existing_content:
        content = f"""#!/bin/bash
# teleclaude-docs-check: Reject hardcoded HOME paths
{PRECOMMIT_CHECK}
"""
        hook_file.write_text(content, encoding="utf-8")
    else:
        check_block = f"""
# teleclaude-docs-check: Reject hardcoded HOME paths
{PRECOMMIT_CHECK}
"""
        with open(hook_file, "a", encoding="utf-8") as f:
            if not existing_content.endswith("\n"):
                f.write("\n")
            f.write(check_block)

    hook_file.chmod(hook_file.stat().st_mode | 0o111)
    print("telec init: git pre-commit hook installed.")
