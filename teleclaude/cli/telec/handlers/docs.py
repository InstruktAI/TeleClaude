"""Handlers for telec docs commands."""

from __future__ import annotations

from pathlib import Path

from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.cli.telec.help import _usage
from teleclaude.config.loader import load_app_config
from teleclaude.context_selector import build_context_output
from teleclaude.core.identity import get_identity_resolver

__all__ = [
    "_handle_docs",
    "_handle_docs_get",
    "_handle_docs_index",
]


def _current_terminal_role() -> str | None:
    email = read_current_session_email()
    if not email:
        return None
    return get_identity_resolver().resolve_by_email(email).person_role


def _handle_docs(args: list[str]) -> None:
    """Handle telec docs commands."""
    if not args:
        print(_usage("docs"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("docs"))
        return

    subcommand = args[0]
    if subcommand == "index":
        _handle_docs_index(args[1:])
    elif subcommand == "get":
        _handle_docs_get(args[1:])
    else:
        print(f"Unknown docs subcommand: {subcommand}")
        print(_usage("docs"))
        raise SystemExit(1)


def _handle_docs_index(args: list[str]) -> None:
    """Handle telec docs index."""
    project_root = Path.cwd()
    baseline_only = False
    third_party = False
    areas: list[str] = []
    domains: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--baseline-only", "-b"):
            baseline_only = True
            i += 1
        elif arg in ("--third-party", "-t"):
            third_party = True
            i += 1
        elif arg in ("--areas", "-a") and i + 1 < len(args):
            areas = [a.strip() for a in args[i + 1].split(",") if a.strip()]
            i += 2
        elif arg in ("--areas", "-a"):
            print("Missing value for --areas.")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        elif arg in ("--domains", "-d") and i + 1 < len(args):
            domains = [d.strip() for d in args[i + 1].split(",") if d.strip()]
            i += 2
        elif arg in ("--domains", "-d"):
            print("Missing value for --domains.")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        else:
            print(f"Unexpected positional argument for docs index: {arg}")
            print(_usage("docs", "index"))
            raise SystemExit(1)

    effective_role = _current_terminal_role()
    config = load_app_config(project_root)
    output = build_context_output(
        areas=areas,
        project_root=project_root,
        snippet_ids=None,
        baseline_only=baseline_only,
        include_third_party=third_party,
        domains=domains,
        effective_human_role=effective_role,
        config=config,
    )
    print(output)


def _handle_docs_get(args: list[str]) -> None:
    """Handle telec docs get."""
    project_root = Path.cwd()
    snippet_ids: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("docs", "get"))
            raise SystemExit(1)
        for part in arg.split(","):
            part = part.strip()
            if part:
                snippet_ids.append(part)
        i += 1

    if not snippet_ids:
        print("At least one snippet ID is required.")
        print(_usage("docs", "get"))
        raise SystemExit(1)

    effective_role = _current_terminal_role()
    config = load_app_config(project_root)
    output = build_context_output(
        areas=[],
        project_root=project_root,
        snippet_ids=snippet_ids,
        baseline_only=False,
        include_third_party=False,
        domains=None,
        effective_human_role=effective_role,
        config=config,
    )
    print(output)
