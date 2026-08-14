"""Handlers for telec bugs commands."""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.api_models import TodoDumpRequest
from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.config import config
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.services.log_bug_hunter_suppressions import (
    Disposition,
    MatchMode,
    Suppression,
    SuppressionLedgerError,
    active,
    append,
    load,
    remove,
    suppressions_path_for,
)
from teleclaude.services.project_catalog.loaders import load_project_node
from teleclaude.slug import normalize_slug
from teleclaude.types.todo_kind import TODO_KIND_BUG

__all__ = [
    "_handle_bugs",
    "_handle_bugs_list",
    "_handle_bugs_report",
    "_handle_bugs_suppress",
    "_handle_bugs_suppressions",
    "_handle_bugs_unsuppress",
    "_resolve_project_by_name",
]


# Hidden acknowledgment token for the pre-filing interrogation gate. Absent
# from `flags`/`args` in the CLI surface table, so it appears in no --help
# output, usage line, or generated docs. The literal appears exactly once,
# here; every other reference in this module reads this constant.
_FILING_ACK_FLAG = "--approved"

_BUG_FILING_GATE = (
    "Nothing was filed. Face these before this bug enters the pipeline (bug-kind\n"
    "todos autostart their prepare lane, so filing is pipeline entry):\n"
    "\n"
    "1. Five-minute rule — small and settled enough to fix directly? Fix it\n"
    "   in-context on main now and dispatch a commit-SHA reviewer\n"
    "   (/next-review-commits); file no bug.\n"
    "\n"
    "2. Duplication — already reported, already being fixed, or a triaged\n"
    "   known issue? Check:\n"
    "     telec todo list\n"
    "     telec bugs list\n"
    "     telec bugs suppressions\n"
    "\n"
    "3. Ordering / dependency — downstream of, or dependent on, work already\n"
    "   in flight? Route it to that lane per the amendment/FYI rules in\n"
    "   software-development/policy/todo-creation-discipline; do not file a\n"
    "   sibling.\n"
    "\n"
    "4. Validity & ownership — organic-trigger evidence in hand (not\n"
    "   speculation from a single log line)? Owning project correct\n"
    "   (--project)?\n"
    "\n"
    "Only once these are faced, file with:\n"
    f"  telec bugs report {_FILING_ACK_FLAG} '<description>' [--slug <slug>] "
    "[--body <text>] [--project <name>] [--human-involved]\n"
)


def _resolve_project_by_name(name: str) -> Path:
    """Resolve a project name to its path using trusted_dirs config."""
    trusted = config.computer.get_all_trusted_dirs()
    for td in trusted:
        if td.name.lower() == name.lower():
            return Path(td.path).expanduser()

    available = sorted({td.name for td in trusted})
    print(f"Unknown project '{name}'. Must be one of:")
    for n in available:
        print(f"  - {n}")
    raise SystemExit(1)


def _resolve_project_slug(project_name: str | None) -> str:
    """Resolve the project slug the suppression ledger is keyed on.

    Mirrors the service's slug derivation (``load_project_node``) so the CLI
    writer and the daemon reader resolve the identical ledger path.
    """
    root = _resolve_project_by_name(project_name) if project_name else resolve_invocation_cwd()
    node = load_project_node(root)
    if node is None:
        print(f"No loadable teleclaude.yml under {root}; cannot resolve project for suppression.")
        raise SystemExit(1)
    return node.slug


def _handle_bugs(args: list[str]) -> None:
    """Handle telec bugs commands."""
    if not args:
        print(_usage("bugs"))
        return

    subcommand = args[0]
    if subcommand == "report":
        _handle_bugs_report(args[1:])
    elif subcommand == "list":
        _handle_bugs_list(args[1:])
    elif subcommand in ("suppress", "suppressions", "unsuppress"):
        # A corrupt durable ledger fails loudly rather than being silently emptied
        # and overwritten; surface it as a clean non-zero exit, not a raw traceback.
        try:
            if subcommand == "suppress":
                _handle_bugs_suppress(args[1:])
            elif subcommand == "suppressions":
                _handle_bugs_suppressions(args[1:])
            else:
                _handle_bugs_unsuppress(args[1:])
        except SuppressionLedgerError as exc:
            print(f"Suppression ledger error: {exc}")
            raise SystemExit(1) from None
    else:
        print(f"Unknown bugs subcommand: {subcommand}")
        print(_usage("bugs"))
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
    human_involved = False
    approved = False
    project_root = resolve_invocation_cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == _FILING_ACK_FLAG:
            approved = True
            i += 1
        elif arg == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        elif arg == "--body" and i + 1 < len(args):
            body = args[i + 1]
            i += 2
        elif arg == "--project" and i + 1 < len(args):
            project_name = args[i + 1]
            i += 2
        elif arg == "--human-involved":
            human_involved = True
            i += 1
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

    # The interrogation gate: a description without the acknowledgment flag
    # is the designed discovery moment (mirrors the sealed-commit gate's
    # discovery semantics) — serving it is the successful outcome, so this
    # exits 0 and files nothing. The gate verifies the pre-filing decisions
    # were faced, never that the answers are true.
    if description and not approved:
        print(_BUG_FILING_GATE, file=sys.stderr, end="")
        return

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

    bug_request = TodoDumpRequest(
        slug=slug,
        content=bug_content,
        kind=TODO_KIND_BUG,
        cwd=str(project_root),
        human_involved=human_involved,
    )
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

    print(f"Created bug: {slug}")


def _handle_bugs_list(args: list[str]) -> None:
    """Handle telec bugs list — queries todos.db for bug-kind todos."""
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

    db = get_todos_db_sync(str(project_root))
    conn = db._sync_conn()
    try:
        rows = conn.execute(
            "SELECT r.slug, s.state FROM todo r "  # guard: raw-sql
            "JOIN todo_state s ON r.id = s.id "
            "WHERE r.status = 'active' "
            "AND json_extract(s.state, '$.kind') = 'bug' "
            "ORDER BY r.updated_at DESC",
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No bugs found")
        return

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


def _parse_expires(raw: str) -> datetime:
    """Parse an ISO-8601 ``--expires`` value, exiting on a malformed input."""
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        print(
            f"Invalid --expires '{raw}': expected an ISO-8601 timestamp (e.g. 2026-12-31 or 2026-12-31T00:00:00+00:00)."
        )
        raise SystemExit(1) from None


def _handle_bugs_suppress(args: list[str]) -> None:
    """Handle telec bugs suppress "<pattern>" --reason <r> [...]."""
    pattern: str | None = None
    reason: str | None = None
    match_raw = MatchMode.SUBSTRING.value
    disposition_raw = Disposition.WONTFIX.value
    project_name: str | None = None
    source_bug: str | None = None
    expires_raw: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--reason" and i + 1 < len(args):
            reason = args[i + 1]
            i += 2
        elif arg == "--match" and i + 1 < len(args):
            match_raw = args[i + 1]
            i += 2
        elif arg == "--disposition" and i + 1 < len(args):
            disposition_raw = args[i + 1]
            i += 2
        elif arg == "--project" and i + 1 < len(args):
            project_name = args[i + 1]
            i += 2
        elif arg == "--source-bug" and i + 1 < len(args):
            source_bug = args[i + 1]
            i += 2
        elif arg == "--expires" and i + 1 < len(args):
            expires_raw = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "suppress"))
            raise SystemExit(1)
        else:
            if pattern is not None:
                print("Only one pattern is allowed.")
                print(_usage("bugs", "suppress"))
                raise SystemExit(1)
            pattern = arg
            i += 1

    if not pattern:
        print("Missing required pattern.")
        print(_usage("bugs", "suppress"))
        raise SystemExit(1)
    if not reason:
        print("Missing required --reason.")
        print(_usage("bugs", "suppress"))
        raise SystemExit(1)

    try:
        match = MatchMode(match_raw)
    except ValueError:
        print(f"Invalid --match '{match_raw}': must be one of {', '.join(m.value for m in MatchMode)}.")
        raise SystemExit(1) from None
    try:
        disposition = Disposition(disposition_raw)
    except ValueError:
        print(f"Invalid --disposition '{disposition_raw}': must be one of {', '.join(d.value for d in Disposition)}.")
        raise SystemExit(1) from None

    if match is MatchMode.REGEX:
        try:
            re.compile(pattern)
        except re.error as exc:
            print(f"Invalid regex pattern: {exc}")
            raise SystemExit(1) from None

    expires_at = _parse_expires(expires_raw) if expires_raw else None
    slug = _resolve_project_slug(project_name)
    entry = Suppression(
        id=uuid.uuid4().hex[:12],
        pattern=pattern,
        match=match,
        disposition=disposition,
        reason=reason,
        source_bug=source_bug,
        created_by=read_current_session_email() or "unknown",
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )
    append(suppressions_path_for(slug), entry)
    print(f"Registered suppression {entry.id} for project '{slug}' ({match.value}: {pattern!r}).")


def _handle_bugs_suppressions(args: list[str]) -> None:
    """Handle telec bugs suppressions [--project <name>] — list the ledger."""
    project_name: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project" and i + 1 < len(args):
            project_name = args[i + 1]
            i += 2
        else:
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "suppressions"))
            raise SystemExit(1)

    slug = _resolve_project_slug(project_name)
    ledger = load(suppressions_path_for(slug))
    entries = active(ledger, datetime.now(UTC))
    if not entries:
        print(f"No active suppressions for project '{slug}'.")
        return

    print(f"Active suppressions for project '{slug}' ({len(entries)}):\n")
    for entry in entries:
        expiry = entry.expires_at.isoformat() if entry.expires_at else "never"
        print(f"  {entry.id}  [{entry.match.value}/{entry.disposition.value}]  expires={expiry}")
        print(f"    pattern: {entry.pattern!r}")
        print(f"    reason:  {entry.reason}")
        if entry.source_bug:
            print(f"    source:  {entry.source_bug}")


def _handle_bugs_unsuppress(args: list[str]) -> None:
    """Handle telec bugs unsuppress <id> [--project <name>] — remove one entry."""
    suppression_id: str | None = None
    project_name: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project" and i + 1 < len(args):
            project_name = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "unsuppress"))
            raise SystemExit(1)
        else:
            if suppression_id is not None:
                print("Only one id is allowed.")
                print(_usage("bugs", "unsuppress"))
                raise SystemExit(1)
            suppression_id = arg
            i += 1

    if not suppression_id:
        print("Missing required suppression id.")
        print(_usage("bugs", "unsuppress"))
        raise SystemExit(1)

    slug = _resolve_project_slug(project_name)
    if remove(suppressions_path_for(slug), suppression_id):
        print(f"Removed suppression {suppression_id} from project '{slug}'.")
    else:
        print(f"No suppression with id '{suppression_id}' for project '{slug}'.")
        raise SystemExit(1)
