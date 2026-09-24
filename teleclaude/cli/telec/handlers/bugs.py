"""Handlers for telec bugs commands."""

from __future__ import annotations

import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from teleclaude.api_models import BugListEntryDTO, TodoDumpRequest
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._creation_gate import CREATION_VALIDITY_GATE_ITEM
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import BUGS_LIST, BUGS_REPORT, BUGS_SUPPRESS, BUGS_SUPPRESSIONS, BUGS_UNSUPPRESS
from teleclaude.cli.tool_client import ToolAPIError, get_resolved_caller, tool_api_request
from teleclaude.config import config
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
_GET_METHOD = "GET"
_BUGS_LIST_PATH = "/todos/bugs"
_CWD_PARAMETER = "cwd"

_BUG_FILING_GATE = (
    "Nothing was filed. Face these before this bug enters the pipeline (bug-kind\n"
    "todos autostart their prepare lane, so filing is pipeline entry):\n"
    "\n"
    f"{CREATION_VALIDITY_GATE_ITEM}\n"
    "- Duplication — already reported, already being fixed, or a triaged\n"
    "   known issue? Check:\n"
    "     telec todo list\n"
    "     telec bugs list\n"
    "     telec bugs suppressions\n"
    "\n"
    "- Ordering / dependency — downstream of, or dependent on, work already\n"
    "   in flight? Route it to that lane per the amendment/FYI rules in\n"
    "   sdlc/policy/todo-creation-discipline; do not file a\n"
    "   sibling.\n"
    "\n"
    "- Evidence & ownership — organic-trigger evidence in hand (not\n"
    "   speculation from a single log line)? Owning project correct\n"
    "   (--project)?\n"
    "\n"
    "Only once these are faced, file with:\n"
    f"  telec bugs report {_FILING_ACK_FLAG} '<description>' [--slug <slug>] "
    "[--body <text>] [--project <name>] [--human-involved]\n"
)
_CALLER_PRINCIPAL_REQUIRED_DETAIL = "The daemon did not resolve a caller principal."


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

    parsed = parse_command_args(BUGS_REPORT, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one description is allowed.")
        print(_usage("bugs", "report"))
        raise SystemExit(1)
    description = positionals[0] if positionals else None
    slug = parsed.value(F.FLAG_BUG_SLUG)
    body = parsed.value(F.FLAG_BUG_BODY)
    project_name = parsed.value(F.FLAG_BUG_PROJECT)
    human_involvement_reason = parsed.value(F.FLAG_HUMAN_INVOLVED)
    approved = parsed.has(F.FLAG_BUG_APPROVED)
    project_root = resolve_invocation_cwd()

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
        human_involved=human_involvement_reason is not None,
        human_involvement_reason=human_involvement_reason,
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
    """Handle telec bugs list."""
    project_root = resolve_invocation_cwd()

    parsed = parse_command_args(BUGS_LIST, args)
    if parsed.positionals:
        print(f"Unexpected argument: {parsed.positionals[0]}")
        print(_usage("bugs", "list"))
        raise SystemExit(1)

    try:
        result = tool_api_request(
            _GET_METHOD,
            _BUGS_LIST_PATH,
            params={_CWD_PARAMETER: str(project_root)},
        )
        bugs = TypeAdapter(list[BugListEntryDTO]).validate_python(result)
    except ToolAPIError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not bugs:
        print("No bugs found")
        return

    print(f"Bug fixes ({len(bugs)}):\n")
    print(f"{'Slug':<40} {'Status':<15}")
    print("-" * 60)
    for bug in bugs:
        print(f"{bug.slug:<40} {bug.status:<15}")


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
    parsed = parse_command_args(BUGS_SUPPRESS, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one pattern is allowed.")
        print(_usage("bugs", "suppress"))
        raise SystemExit(1)
    pattern = positionals[0] if positionals else None
    reason = parsed.value(F.FLAG_SUPPRESS_REASON)
    match_raw = parsed.value(F.FLAG_SUPPRESS_MATCH) or MatchMode.SUBSTRING.value
    disposition_raw = parsed.value(F.FLAG_SUPPRESS_DISPOSITION) or Disposition.WONTFIX.value
    project_name = parsed.value(F.FLAG_PROJECT_TRUSTED)
    source_bug = parsed.value(F.FLAG_SUPPRESS_SOURCE_BUG)
    expires_raw = parsed.value(F.FLAG_SUPPRESS_EXPIRES)

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
    try:
        principal = get_resolved_caller().principal
    except ToolAPIError as exc:
        print(exc.message)
        raise SystemExit(1) from exc
    if not principal:
        print(_CALLER_PRINCIPAL_REQUIRED_DETAIL)
        raise SystemExit(1)

    entry = Suppression(
        id=uuid.uuid4().hex[:12],
        pattern=pattern,
        match=match,
        disposition=disposition,
        reason=reason,
        source_bug=source_bug,
        created_by=principal,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
    )
    append(suppressions_path_for(slug), entry)
    print(f"Registered suppression {entry.id} for project '{slug}' ({match.value}: {pattern!r}).")


def _handle_bugs_suppressions(args: list[str]) -> None:
    """Handle telec bugs suppressions [--project <name>] — list the ledger."""
    parsed = parse_command_args(BUGS_SUPPRESSIONS, args)
    if parsed.positionals:
        print(f"Unknown option: {parsed.positionals[0]}")
        print(_usage("bugs", "suppressions"))
        raise SystemExit(1)
    project_name = parsed.value(F.FLAG_PROJECT_TRUSTED)

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
    parsed = parse_command_args(BUGS_UNSUPPRESS, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one id is allowed.")
        print(_usage("bugs", "unsuppress"))
        raise SystemExit(1)
    suppression_id = positionals[0] if positionals else None
    project_name = parsed.value(F.FLAG_PROJECT_TRUSTED)

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
