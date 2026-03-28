"""Handlers for telec todo commands."""
# pylint: disable=import-outside-toplevel,too-many-branches,too-many-locals,too-many-statements
# pylint: disable=no-else-raise,broad-exception-caught

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.todo_scaffold import create_todo_skeleton

__all__ = [
    "_handle_todo",
    "_handle_todo_dump",
    "_handle_todo_from_main",
    "_handle_todo_mark_ready",
    "_handle_todo_remove",
    "_handle_todo_split",
    "_handle_todo_validate",
    "_handle_todo_verify_artifacts",
]


def _handle_todo_mark_ready(args: list[str]) -> None:
    """Handle telec todo mark-ready <slug> [<slug> ...].

    Fast-track one or more TODOs to work-ready state, bypassing the full prepare lifecycle.
    Validates required artifacts exist, then targets the 'prepared' state which stamps
    DOR, grounding, and review verdicts.
    """
    from teleclaude.core.next_machine.state_io import mark_phase

    if not args:
        print("Usage: telec todo mark-ready <slug> [<slug> ...]")
        raise SystemExit(1)

    slugs = [a for a in args if not a.startswith("-")]
    if not slugs:
        print("Missing required argument: <slug>")
        raise SystemExit(1)

    cwd = str(Path.cwd())
    failed = 0
    for slug in slugs:
        try:
            mark_phase(cwd, slug, "prepared")
            print(f"✓ {slug} fast-tracked to work-ready (prepared)")
        except (ValueError, FileNotFoundError) as exc:
            print(str(exc))
            failed += 1

    if failed:
        raise SystemExit(1)


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    from teleclaude.cli.telec.handlers.demo import _handle_todo_demo
    from teleclaude.cli.tool_commands import (
        handle_todo_create,
        handle_todo_integrate,
        handle_todo_mark_phase,
        handle_todo_prepare,
        handle_todo_set_deps,
        handle_todo_work,
    )

    if not args:
        print(_usage("todo"))
        return

    subcommand = args[0]
    if subcommand == "co-create":
        handle_todo_create(args[1:])
    elif subcommand == "remove":
        _handle_todo_remove(args[1:])
    elif subcommand == "validate":
        _handle_todo_validate(args[1:])
    elif subcommand == "demo":
        _handle_todo_demo(args[1:])
    elif subcommand == "prepare":
        handle_todo_prepare(args[1:])
    elif subcommand == "work":
        handle_todo_work(args[1:])
    elif subcommand == "integrate":
        handle_todo_integrate(args[1:])
    elif subcommand == "mark-phase":
        handle_todo_mark_phase(args[1:])
    elif subcommand == "set-deps":
        handle_todo_set_deps(args[1:])
    elif subcommand == "verify-artifacts":
        _handle_todo_verify_artifacts(args[1:])
    elif subcommand == "dump":
        _handle_todo_dump(args[1:])
    elif subcommand == "split":
        _handle_todo_split(args[1:])
    elif subcommand == "mark-ready":
        _handle_todo_mark_ready(args[1:])
    elif subcommand == "from-main":
        _handle_todo_from_main(args[1:])
    else:
        print(f"Unknown todo subcommand: {subcommand}")
        print(_usage("todo"))
        raise SystemExit(1)


def _handle_todo_validate(args: list[str]) -> None:
    """Handle telec todo validate."""

    from teleclaude.resource_validation import validate_all_todos, validate_todo

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "validate"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed for validation.")
                print(_usage("todo", "validate"))
                raise SystemExit(1)
            slug = arg
            i += 1

    errors = []
    if slug:
        errors = validate_todo(slug, project_root)
    else:
        errors = validate_all_todos(project_root)

    if errors:
        print("Todo validation failed:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if slug:
        print(f"✓ Todo {slug} is valid")
    else:
        print("✓ All active todos are valid")


def _handle_todo_verify_artifacts(args: list[str]) -> None:
    """Handle telec todo verify-artifacts <slug> --phase <build|review>."""
    from teleclaude.core.next_machine.core import is_bug_todo, verify_artifacts

    slug: str | None = None
    phase: str | None = None
    cwd = str(Path.cwd())

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--phase",) and i + 1 < len(args):
            phase = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "verify-artifacts"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "verify-artifacts"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if slug is None:
        print("Missing required argument: <slug>")
        print(_usage("todo", "verify-artifacts"))
        raise SystemExit(1)
    if phase is None:
        print("Missing required flag: --phase <build|review>")
        print(_usage("todo", "verify-artifacts"))
        raise SystemExit(1)
    if phase not in ("build", "review"):
        print(f"Invalid phase: {phase!r} (expected 'build' or 'review')")
        raise SystemExit(1)

    is_bug = is_bug_todo(cwd, slug)
    passed, report = verify_artifacts(cwd, slug, phase, is_bug=is_bug)
    print(report)
    raise SystemExit(0 if passed else 1)


def _handle_todo_dump(args: list[str]) -> None:
    """Handle telec todo dump <slug> <content> [--after <deps>]."""
    if len(args) < 2:
        print(_usage("todo", "dump"))
        return

    slug: str | None = None
    content: str | None = None
    project_root = Path.cwd()
    after: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "dump"))
            raise SystemExit(1)
        else:
            if slug is None:
                slug = arg
            elif content is None:
                content = arg
            else:
                print("Too many positional arguments.")
                print(_usage("todo", "dump"))
                raise SystemExit(1)
            i += 1

    if not slug or not content:
        print(_usage("todo", "dump"))
        raise SystemExit(1)

    # Always register in roadmap (unlike create, which only registers with --after)
    after_deps = after if after is not None else []

    expected_input = f"# {slug} — Input\n\n{content}\n"
    todo_dir = project_root / "todos" / slug
    input_path = todo_dir / "input.md"

    if todo_dir.exists():
        if input_path.exists() and input_path.read_text(encoding="utf-8") == expected_input:
            print(f"Todo '{slug}' already scaffolded with same content — retrying commit.")
        else:
            print(f"Error: Todo '{slug}' already exists with different content.")
            raise SystemExit(1)
    else:
        try:
            todo_dir = create_todo_skeleton(project_root, slug, after=after_deps)
        except ValueError as exc:
            print(f"Error: {exc}")
            raise SystemExit(1) from exc
        input_path.write_text(expected_input, encoding="utf-8")

    # Auto-commit bookkeeping on main
    from teleclaude.core.next_machine.worktrees import commit_bookkeeping_to_main

    _ok, _reason = commit_bookkeeping_to_main(
        str(project_root),
        [f"todos/{slug}", "todos/roadmap.yaml"],
        f"chore(todos): dump {slug}",
    )
    if not _ok:
        if _reason == "index_locked":
            lock_path = project_root / ".git" / "index.lock"
            print(
                f"Error: bookkeeping commit blocked by stale git lock.\n"
                f"  Recovery: verify no git process is running, then:\n"
                f"    rm {lock_path}\n"
                f"    telec todo dump {slug} <content>\n"
                f"  The command is idempotent — re-running is safe."
            )
        elif _reason == "push_failed":
            print(
                f"Error: bookkeeping committed locally but push to origin/main FAILED.\n"
                f"  The todo '{slug}' exists on local main but NOT on origin/main.\n"
                f"  Worktrees branch from origin/main — without the push, prepare will fail.\n"
                f"  Recovery:\n"
                f"    git push origin main\n"
                f"    telec todo dump {slug} <content>\n"
                f"  The command is idempotent — re-running is safe.\n"
                f"  If push conflicts: git pull --rebase origin main && git push origin main"
            )
        else:
            print(
                f"Error: bookkeeping commit failed ({_reason}).\n"
                f"  Recovery: fix the issue and re-run:\n"
                f"    telec todo dump {slug} <content>\n"
                f"  The command is idempotent — re-running is safe."
            )
        raise SystemExit(1)

    # Emit planning.todo_dumped notification via daemon API
    _log = get_logger(__name__)
    try:
        envelope = EventEnvelope(
            event="domain.software-development.planning.todo_dumped",
            source="telec-cli",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            description=f"Todo dumped: {slug}",
            payload={"slug": slug, "project_root": str(project_root)},
        )
        tool_api_request("POST", "/events/emit", json_body=envelope.model_dump(mode="json"), timeout=5.0)
        _log.info("Dumped todo: todos/%s/ — notification sent.", slug)
    except Exception:
        _log.warning("Dumped todo: todos/%s/ — notification emission failed", slug)

    # --- Commit and push scaffold to remote ---
    from teleclaude.core.next_machine.worktrees import _ensure_todo_on_remote_main

    pushed, reason = _ensure_todo_on_remote_main(str(project_root), slug)
    if pushed:
        print(f"Scaffold for {slug} pushed to remote: {reason}")
    elif reason not in ("already_on_remote", "no_local_artifacts", "not_a_repo"):
        print(f"Warning: Scaffold for {slug} not pushed to remote: {reason}")


def _handle_todo_split(args: list[str]) -> None:
    """Handle telec todo split <slug> --into <child1> [<child2> ...]."""
    from teleclaude.todo_scaffold import split_todo

    if not args:
        print(_usage("todo", "split"))
        return

    slug: str | None = None
    children: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--into" and i + 1 < len(args):
            i += 1
            children.append(args[i])
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "split"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one parent slug is allowed.")
                print(_usage("todo", "split"))
                raise SystemExit(1)
            slug = arg
        i += 1

    if not slug:
        print("Missing required argument: <slug>")
        print(_usage("todo", "split"))
        raise SystemExit(1)

    if not children:
        print("Missing required flag: --into <child> (at least one)")
        print(_usage("todo", "split"))
        raise SystemExit(1)

    project_root = Path.cwd()
    try:
        created = split_todo(project_root, slug, children)
        print(f"Split '{slug}' into {len(created)} children: {', '.join(children)}")
        for d in created:
            print(f"  Created: {d}")

        # --- Commit and push scaffold to remote ---
        from teleclaude.core.next_machine.worktrees import _ensure_todo_on_remote_main

        pushed, reason = _ensure_todo_on_remote_main(str(project_root), slug)
        if pushed:
            print(f"Parent '{slug}' update pushed to remote: {reason}")
        elif reason not in ("already_on_remote", "no_local_artifacts", "not_a_repo"):
            print(f"Warning: Parent '{slug}' scaffold not pushed to remote: {reason}")

        for child in children:
            pushed, reason = _ensure_todo_on_remote_main(str(project_root), child)
            if pushed:
                print(f"Child '{child}' pushed to remote: {reason}")
            elif reason not in ("already_on_remote", "no_local_artifacts", "not_a_repo"):
                print(f"Warning: Child '{child}' scaffold not pushed to remote: {reason}")
    except (FileNotFoundError, ValueError, FileExistsError) as e:
        print(f"Error: {e}")
        raise SystemExit(1) from e

    # Auto-commit bookkeeping on main
    from teleclaude.core.next_machine.worktrees import commit_bookkeeping_to_main

    commit_paths = [f"todos/{slug}", "todos/roadmap.yaml"]
    for child in children:
        commit_paths.append(f"todos/{child}")
    _ok, _reason = commit_bookkeeping_to_main(
        str(project_root),
        commit_paths,
        f"chore(todos): split {slug}",
    )
    if not _ok:
        if _reason == "push_failed":
            print(
                "Error: split committed locally but push to origin/main FAILED.\n"
                "  Child todos exist on local main but NOT on origin/main.\n"
                "  Recovery:\n"
                "    git push origin main\n"
                "  If push conflicts: git pull --rebase origin main && git push origin main"
            )
            raise SystemExit(1)
        if _reason in ("commit_failed", "not_a_repo"):
            print(
                f"Error: bookkeeping commit failed ({_reason}).\n"
                f"  Recovery: fix the issue and re-run:\n"
                f"    telec todo split {slug} --into {' '.join(children)}"
            )
            raise SystemExit(1)


def _handle_todo_remove(args: list[str]) -> None:
    """Handle telec todo remove."""
    from teleclaude.todo_scaffold import remove_todo

    if not args:
        print(_usage("todo", "remove"))
        return

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "remove"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "remove"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "remove"))
        raise SystemExit(1)

    try:
        remove_todo(project_root, slug)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Removed todo: {slug}")

    # Auto-commit bookkeeping on main (stages deletion + roadmap change)
    from teleclaude.core.next_machine.worktrees import commit_bookkeeping_to_main

    _ok, _reason = commit_bookkeeping_to_main(
        str(project_root),
        [f"todos/{slug}", "todos/roadmap.yaml"],
        f"chore(todos): remove {slug}",
    )
    if not _ok and _reason in ("commit_failed", "not_a_repo"):
        print(f"Warning: bookkeeping commit skipped ({_reason})")


def _handle_todo_from_main(args: list[str]) -> None:
    """Handle telec todo from-main --slug <name> [--description <desc>] [--all]."""
    from teleclaude.todo_scaffold import create_from_main_skeleton

    slug: str | None = None
    description: str | None = None
    all_files = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        elif arg == "--description" and i + 1 < len(args):
            description = args[i + 1]
            i += 2
        elif arg == "--all":
            all_files = True
            i += 1
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "from-main"))
            raise SystemExit(1)
        else:
            print(f"Unexpected argument: {arg}")
            print(_usage("todo", "from-main"))
            raise SystemExit(1)

    if not slug:
        print("Missing required flag: --slug <name>")
        print(_usage("todo", "from-main"))
        raise SystemExit(1)

    project_root = str(Path.cwd())
    try:
        output = create_from_main_skeleton(project_root, slug, description=description, all_files=all_files)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(output)
