"""Handlers for telec bugs commands."""
# pylint: disable=import-outside-toplevel,too-many-locals,too-many-branches,too-many-statements
# pylint: disable=raise-missing-from,no-else-raise,broad-exception-caught

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDumpRequest
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.events.envelope import EventEnvelope, EventLevel
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.slug import normalize_slug

_log = get_logger(__name__)

__all__ = [
    "_handle_bugs",
    "_handle_bugs_create",
    "_handle_bugs_list",
    "_handle_bugs_report",
    "_resolve_project_by_name",
]


def _emit_bug_dumped_event(slug: str, project_root: Path) -> None:
    """Emit ``todo_dumped`` with ``kind=bug`` so the lifecycle router dispatches.

    The lifecycle router owns ``/next-work`` dispatch for bug lanes; the CLI
    only publishes the intent via the event and lets the router decide.
    """
    try:
        envelope = EventEnvelope(
            event="domain.software-development.planning.todo_dumped",
            source="telec-cli",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            description=f"Bug dumped: {slug}",
            payload={"slug": slug, "kind": "bug", "project_root": str(project_root)},
        )
        tool_api_request("POST", "/events/emit", json_body=envelope.model_dump(mode="json"), timeout=5.0)
    except Exception:
        _log.warning("Bug dumped but notification emission failed: %s", slug)


def _resolve_project_by_name(name: str) -> Path:
    """Resolve a project name to its path using trusted_dirs config."""
    from teleclaude.config import config  # pylint: disable=import-outside-toplevel

    trusted = config.computer.get_all_trusted_dirs()
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
    if not args:
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)

    slug: str | None = None
    project_name: str | None = None
    project_root = resolve_invocation_cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project" and i + 1 < len(args):
            project_name = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec bugs create <slug>")
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print("Usage: telec bugs create <slug>")
                raise SystemExit(1)
            slug = arg
            i += 1

    if project_name:
        project_root = _resolve_project_by_name(project_name)

    if slug is None:
        print("Error: slug is required")
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)

    request = TodoDumpRequest(slug=slug, content="", kind="bug", cwd=str(project_root))
    result = tool_api_request(
        "POST",
        "/todos/dump",
        json_body=request.model_dump(mode="json"),
        timeout=10.0,
    )
    if isinstance(result, dict) and result.get("status") == "ok":
        _emit_bug_dumped_event(slug, project_root)
        print(f"Created bug: {slug}")
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(f"Error: {result}")
        raise SystemExit(1)


def _handle_bugs_report(args: list[str]) -> None:
    """Handle telec bugs report <description> [--slug <slug>]."""
    if not args:
        print(_usage("bugs", "report"))
        return

    description: str | None = None
    slug: str | None = None
    body: str | None = None
    project_name: str | None = None
    project_root = resolve_invocation_cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        elif arg == "--body" and i + 1 < len(args):
            body = args[i + 1]
            i += 2
        elif arg == "--project" and i + 1 < len(args):
            project_name = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "report"))
            raise SystemExit(1)
        else:
            if description is not None:
                print("Only one description is allowed.")
                print(_usage("bugs", "report"))
                raise SystemExit(1)
            description = arg
            i += 1

    if project_name:
        project_root = _resolve_project_by_name(project_name)

    if not description:
        print("Missing required description.")
        print(_usage("bugs", "report"))
        raise SystemExit(1)

    # Auto-generate slug if not provided
    if not slug:
        slug_base = normalize_slug(description)
        if len(slug_base) > 40:
            slug_base = slug_base[:40].rstrip("-")
        slug = f"fix-{slug_base}"

    # Build bug content from description + body
    bug_content = f"# {slug}\n\n**Symptom:** {description}\n"
    if body:
        bug_content += f"\n{body}\n"

    bug_request = TodoDumpRequest(slug=slug, content=bug_content, kind="bug", cwd=str(project_root))
    api_result = tool_api_request(
        "POST",
        "/todos/dump",
        json_body=bug_request.model_dump(mode="json"),
        timeout=10.0,
    )
    if not (isinstance(api_result, dict) and api_result.get("status") == "ok"):
        detail = api_result.get("detail", api_result) if isinstance(api_result, dict) else api_result
        print(f"Error: {detail}")
        raise SystemExit(1)

    _emit_bug_dumped_event(slug, project_root)
    print(f"Created bug: {slug}")


def _handle_bugs_list(args: list[str]) -> None:
    """Handle telec bugs list — queries todos.db for bug-kind todos."""
    from teleclaude.core.next_machine.state_io import _get_todos_db_sync  # pylint: disable=import-outside-toplevel

    project_root = resolve_invocation_cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)
        else:
            print(f"Unexpected argument: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)

    db = _get_todos_db_sync(str(project_root))
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        rows = conn.execute(
            "SELECT r.slug, s.state FROM roadmap r "  # guard: raw-sql
            "JOIN todo_state s ON r.id = s.id "
            "WHERE r.status = 'active' "
            "AND json_extract(s.state, '$.kind') = 'bug' "
            "ORDER BY r.position",
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No bugs found")
        return

    import json  # pylint: disable=import-outside-toplevel

    bugs: list[tuple[str, str]] = []
    for slug, state_json in rows:
        state = json.loads(state_json) if state_json else {}
        phase = str(state.get("phase", "pending"))
        build_review = state.get("build_review", {})
        finalize = state.get("finalize", {})

        verdict = str(build_review.get("verdict", "")) if isinstance(build_review, dict) else ""
        finalize_status = str(finalize.get("status", "")) if isinstance(finalize, dict) else ""

        if verdict == "approve" or finalize_status not in ("", "pending"):
            status = "approved"
        elif verdict == "changes_requested":
            status = "fixing"
        elif phase in ("build_complete", "review_pending"):
            status = "reviewing"
        elif phase == "build_started":
            status = "building"
        else:
            status = "pending"

        bugs.append((slug, status))

    print(f"Bug fixes ({len(bugs)}):\n")
    print(f"{'Slug':<40} {'Status':<15}")
    print("-" * 60)
    for slug, status in bugs:
        print(f"{slug:<40} {status:<15}")
