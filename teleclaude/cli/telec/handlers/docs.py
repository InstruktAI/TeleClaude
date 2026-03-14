"""Handlers for telec docs commands."""

from __future__ import annotations

from teleclaude.cli.telec.help import _usage

__all__ = [
    "_handle_docs",
    "_handle_docs_get",
    "_handle_docs_index",
]


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
    from pathlib import Path

    from teleclaude.context_selector import build_context_output

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

    from teleclaude.cli.session_auth import resolve_cli_caller_role

    effective_role = resolve_cli_caller_role()
    output = build_context_output(
        areas=areas,
        project_root=project_root,
        snippet_ids=None,
        baseline_only=baseline_only,
        include_third_party=third_party,
        domains=domains,
        effective_human_role=effective_role,
    )
    print(output)


def _handle_docs_get(args: list[str]) -> None:
    """Handle telec docs get."""
    from pathlib import Path

    from teleclaude.context_selector import build_context_output

    project_root = Path.cwd()
    snippet_ids: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("docs", "get"))
            raise SystemExit(1)
        else:
            for part in arg.split(","):
                part = part.strip()
                if part:
                    snippet_ids.append(part)
            i += 1

    if not snippet_ids:
        print("At least one snippet ID is required.")
        print(_usage("docs", "get"))
        raise SystemExit(1)

    from teleclaude.cli.session_auth import resolve_cli_caller_role

    effective_role = resolve_cli_caller_role()
    output = build_context_output(
        areas=[],
        project_root=project_root,
        snippet_ids=snippet_ids,
        baseline_only=False,
        include_third_party=False,
        domains=None,
        effective_human_role=effective_role,
    )
    print(output)
