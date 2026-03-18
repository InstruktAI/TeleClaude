"""Handlers for telec bugs commands."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

import yaml

import teleclaude.config as teleclaude_config
from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.models import CreateSessionResult
from teleclaude.cli.telec.help import _usage
from teleclaude.constants import WORKTREE_DIR
from teleclaude.slug import normalize_slug
from teleclaude.todo_scaffold import create_bug_skeleton

__all__ = [
    "_handle_bugs",
    "_handle_bugs_create",
    "_handle_bugs_list",
    "_handle_bugs_report",
    "_resolve_project_by_name",
]


def _ensure_todo_on_remote_main_func(project_root: Path, slug: str) -> tuple[bool, str]:
    """Resolve the remote-sync helper lazily so tests can monkeypatch it."""
    worktrees = importlib.import_module("teleclaude.core.next_machine.worktrees")
    ensure_todo = worktrees._ensure_todo_on_remote_main
    return ensure_todo(str(project_root), slug)


def _resolve_project_by_name(name: str) -> Path:
    """Resolve a project name to its path using trusted_dirs config."""
    trusted = teleclaude_config.config.computer.get_all_trusted_dirs()
    for td in trusted:
        if td.name.lower() == name.lower():
            return Path(td.path).expanduser()

    available = sorted({td.name for td in trusted})
    print(f"Unknown project '{name}'. Must be one of:")
    for n in available:
        print(f"  - {n}")
    raise SystemExit(1)


def _handle_bugs(args: list[str]) -> None:
    """Handle telec bugs commands."""
    if not args:
        print(_usage("bugs"))
        return

    subcommand = args[0]
    if subcommand == "report":
        _handle_bugs_report(args[1:])
    elif subcommand == "create":
        _handle_bugs_create(args[1:])
    elif subcommand == "list":
        _handle_bugs_list(args[1:])
    else:
        print(f"Unknown bugs subcommand: {subcommand}")
        print(_usage("bugs"))
        raise SystemExit(1)


def _handle_bugs_create(args: list[str]) -> None:
    """Handle telec bugs create <slug>."""
    project_root = Path.cwd()
    slug, project_name = _parse_bug_create_args(args)

    if project_name:
        project_root = _resolve_project_by_name(project_name)

    try:
        bug_dir = create_bug_skeleton(
            project_root=project_root,
            slug=slug,
            description="",
        )
        print(f"Created bug skeleton: {bug_dir}")
        _maybe_report_remote_push(project_root, slug)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


def _handle_bugs_report(args: list[str]) -> None:
    """Handle telec bugs report <description> [--slug <slug>]."""
    if not args:
        print(_usage("bugs", "report"))
        return

    description, slug, body, project_name = _parse_bug_report_args(args)
    project_root = Path.cwd()

    if project_name:
        project_root = _resolve_project_by_name(project_name)

    resolved_slug = _resolve_bug_slug(description, slug)

    try:
        todo_dir = create_bug_skeleton(
            project_root,
            resolved_slug,
            description,
            body=body or "",
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    slug = todo_dir.name

    _maybe_report_remote_push(project_root, slug)

    try:
        result = _dispatch_bug_fix(project_root, slug)
        print(f"Created bug todo: {todo_dir}")
        print(f"Bug slug: {slug}")
        print(f"Orchestrator session: {result.session_id}")
    except (APIError, OSError, RuntimeError, TypeError, ValueError) as exc:
        _report_orchestrator_dispatch_failure(todo_dir, slug, exc)


def _handle_bugs_list(args: list[str]) -> None:
    """Handle telec bugs list."""
    _reject_bug_list_args(args)
    project_root = Path.cwd()
    todos_dir = project_root / "todos"
    if not todos_dir.exists():
        print("No bugs found")
        return

    bugs = _collect_bug_rows(project_root, todos_dir)

    if not bugs:
        print("No bugs found")
        return

    print(f"Bug fixes ({len(bugs)}):\n")
    print(f"{'Slug':<40} {'Status':<15}")
    print("-" * 60)
    for slug, status in bugs:
        print(f"{slug:<40} {status:<15}")


def _parse_bug_create_args(args: list[str]) -> tuple[str, str | None]:
    if not args:
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)

    slug: str | None = None
    project_name: str | None = None
    index = 0

    while index < len(args):
        arg = args[index]
        if arg == "--project" and index + 1 < len(args):
            project_name = args[index + 1]
            index += 2
            continue
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec bugs create <slug>")
            raise SystemExit(1)
        if slug is not None:
            print("Only one slug is allowed.")
            print("Usage: telec bugs create <slug>")
            raise SystemExit(1)
        slug = arg
        index += 1

    if slug is None:
        print("Error: slug is required")
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)
    return slug, project_name


def _parse_bug_report_args(args: list[str]) -> tuple[str, str | None, str | None, str | None]:
    description: str | None = None
    slug: str | None = None
    body: str | None = None
    project_name: str | None = None
    index = 0

    while index < len(args):
        arg = args[index]
        if arg == "--slug" and index + 1 < len(args):
            slug = args[index + 1]
            index += 2
            continue
        if arg == "--body" and index + 1 < len(args):
            body = args[index + 1]
            index += 2
            continue
        if arg == "--project" and index + 1 < len(args):
            project_name = args[index + 1]
            index += 2
            continue
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "report"))
            raise SystemExit(1)
        if description is not None:
            print("Only one description is allowed.")
            print(_usage("bugs", "report"))
            raise SystemExit(1)
        description = arg
        index += 1

    if not description:
        print("Missing required description.")
        print(_usage("bugs", "report"))
        raise SystemExit(1)
    return description, slug, body, project_name


def _resolve_bug_slug(description: str, slug: str | None) -> str:
    if slug:
        return slug

    slug_base = normalize_slug(description)
    if len(slug_base) > 40:
        slug_base = slug_base[:40].rstrip("-")
    return f"fix-{slug_base}"


def _maybe_report_remote_push(project_root: Path, slug: str) -> None:
    pushed, reason = _ensure_todo_on_remote_main_func(project_root, slug)
    if pushed:
        print(f"Scaffold for {slug} pushed to remote: {reason}")
        return
    if reason not in ("already_on_remote", "no_local_artifacts", "not_a_repo"):
        print(f"Warning: Scaffold for {slug} not pushed to remote: {reason}")


async def _run_bug_fix_session(project_root: Path, slug: str) -> CreateSessionResult:
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.run_session(
            command="/next-work",
            args=slug,
            project_path=str(project_root),
            agent="claude",
            thinking_mode="slow",
            detach=True,
        )
    finally:
        await api.close()


def _dispatch_bug_fix(project_root: Path, slug: str) -> CreateSessionResult:
    return asyncio.run(_run_bug_fix_session(project_root, slug))


def _report_orchestrator_dispatch_failure(todo_dir: Path, slug: str, exc: Exception) -> None:
    print(f"Error dispatching orchestrator: {exc}")
    print(f"Bug scaffold created at {todo_dir}.")
    print(
        "Start orchestrator manually: telec sessions run "
        f"--command /next-work --args {slug} --agent claude --mode slow --detach"
    )


def _reject_bug_list_args(args: list[str]) -> None:
    for arg in args:
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)
        print(f"Unexpected argument: {arg}")
        print(_usage("bugs", "list"))
        raise SystemExit(1)


def _collect_bug_rows(project_root: Path, todos_dir: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for todo_dir in sorted(todos_dir.iterdir()):
        if not todo_dir.is_dir() or todo_dir.name.startswith("."):
            continue
        if not (todo_dir / "bug.md").exists():
            continue
        rows.append((todo_dir.name, _read_bug_status(project_root, todo_dir)))
    return rows


def _read_bug_status(project_root: Path, todo_dir: Path) -> str:
    state_yaml = todo_dir / "state.yaml"
    worktree_state = project_root / WORKTREE_DIR / todo_dir.name / "todos" / todo_dir.name / "state.yaml"
    state_path = worktree_state if worktree_state.exists() else state_yaml
    if not state_path.exists():
        return "unknown"

    try:
        state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return "unknown"
    return _status_from_state(state)


def _status_from_state(state: Any) -> str:
    if not isinstance(state, dict):
        return "unknown"

    build = state.get("build", "pending")
    review = state.get("review", "pending")

    if review == "approved":
        return "approved"
    if review == "changes_requested":
        return "fixing"
    if build == "complete":
        return "reviewing"
    if build in ("started", "complete"):
        return "building"
    return "pending"
