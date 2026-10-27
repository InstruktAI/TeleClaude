"""Handlers for telec bugs commands."""

from __future__ import annotations

import re
import sys
import uuid
from datetime import UTC, datetime
from http import HTTPMethod
from pathlib import Path
from typing import TYPE_CHECKING

from teleclaude.caller_identity import NoIdentityCliCaller, Platform, ProjectPath
from teleclaude.cli.session_auth import no_identity_refusal, require_cli_clearance, resolve_cli_identity
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import addressed_computer, project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._creation_gate import CREATION_VALIDITY_GATE_ITEM
from teleclaude.cli.telec.handlers._todo_read import run_todo_read
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import BUGS_LIST, BUGS_REPORT, BUGS_SUPPRESS, BUGS_SUPPRESSIONS, BUGS_UNSUPPRESS
from teleclaude.cli.telec.surface_types import CommandAuth
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.project_root import resolve_invocation_cwd, resolve_invocation_roots
from teleclaude.services.log_bug_hunter_suppressions import (
    Disposition,
    MatchMode,
    Suppression,
    SuppressionLedgerError,
    active,
    append,
    load,
    new_suppression,
    remove,
    suppressions_path_for,
)
from teleclaude.types.todo_kind import TodoKind

if TYPE_CHECKING:
    from teleclaude.api_models import BugListEntryDTO
    from teleclaude.core.workflow_store.store import WorkflowStore

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
_BUGS_REPORT_PATH = "bugs report"
_BUGS_PATH = "/bugs"
_BUG_FILING_PATH = "/todos/dump"
_JSON_DUMP_MODE = "json"
_SUPPRESSIONS_PATH = "/bugs/suppressions"
_UNEXPECTED_RESPONSE = "unexpected bugs response: {answer}"
_BUGS_SUPPRESS_PATH = "bugs suppress"
_BUGS_SUPPRESSIONS_PATH = "bugs suppressions"
_BUGS_UNSUPPRESS_PATH = "bugs unsuppress"
_REGISTERED_PROJECTS_HEADING = "Registered projects:"
_UNKNOWN_PROJECT_IDENTITY_ROW = "  - {identity}"
_BUG_FILING_GATE = (
    "Nothing was filed. Face these before this bug enters the pipeline (bug-kind\n"
    "todos autostart their prepare lane, so filing is pipeline entry):\n"
    "\n"
    "- Bug or change — which current contract does this behavior break? A\n"
    "   failure proves something happened, not that it is wrong; a bug is\n"
    "   behavior a current contract states otherwise, and its fix restores what\n"
    "   that contract says. State the contract and how the behavior breaks it in\n"
    "   the report. Where no current contract states the behavior you expected,\n"
    "   this is not a bug, however real the failure: file it as a change only\n"
    "   when that behavior is wanted, and otherwise file nothing:\n"
    "     telec todo create <slug> <content> --kind change\n"
    "   The prepare orchestrator rejects a report of behavior no current\n"
    "   contract states otherwise, and reclassifies it to a change only when\n"
    "   it asks for wanted behavior.\n"
    "   A report whose premise is that nothing followed up: first establish\n"
    "   whether the sanctioned recovery was attempted. An unattempted recovery\n"
    "   is operational work and creates no todo; a request to change the\n"
    "   recovery contract itself is a change.\n"
    "   Authority: sdlc/policy/todo-creation-discipline.\n"
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
    "   sdlc/policy/todo-creation-discipline.\n"
    "\n"
    "- Evidence & ownership — an occurrence or a dangerous path in hand\n"
    "   (sdlc/concept/defect-evidence)? Owning project correct\n"
    "   (--project)? A symptom that stops once the observing project's own\n"
    "   configuration matches a TeleClaude default (a .gitignore entry, a\n"
    "   blessed template line) is that project's to fix, there.\n"
    "   Put the observations and their addresses first. Keep any causal\n"
    "   account apart from them: each transition with its evidence, the\n"
    "   alternatives checked, and what remains unknown, or the statement that\n"
    "   the cause is not established. Preparation can confirm a present\n"
    "   account against its sources and skip the diagnosis peer.\n"
    "\n"
    "Only once these are faced, file with:\n"
    f"  telec bugs report {_FILING_ACK_FLAG} '<description>' [--slug <slug>] "
    "[--body <text>] [--project <name>] [--human-involved]\n"
)


def _resolve_project_by_name(name: str, command_path: str) -> Path:
    """Resolve a project identity/display name, then clear its exact root."""
    from teleclaude.services.project_catalog import (  # noqa: PLC0415 - project lookup belongs to bug filing.
        get_project_catalog_service,
    )

    catalog = get_project_catalog_service()
    catalog.refresh()
    projects = catalog.list_projects()
    requested = name.casefold()
    for project in projects:
        if requested in (project.slug.casefold(), project.name.casefold()):
            require_cli_clearance(
                command_path,
                auth=_command_auth(command_path),
                role_target=ProjectPath(project.root),
            )
            return project.root

    require_cli_clearance(command_path, auth=_command_auth(command_path), role_target=Platform())
    available = sorted({project.slug for project in projects})
    print(unregistered_referent(ReferentKind.PROJECT, name))
    print(_REGISTERED_PROJECTS_HEADING)
    for identity in available:
        print(_UNKNOWN_PROJECT_IDENTITY_ROW.format(identity=identity))
    raise SystemExit(1)


def _command_auth(command_path: str) -> CommandAuth:
    """Return the declared authorization for a bug command path."""
    command = {
        _BUGS_REPORT_PATH: BUGS_REPORT,
        _BUGS_SUPPRESS_PATH: BUGS_SUPPRESS,
        _BUGS_SUPPRESSIONS_PATH: BUGS_SUPPRESSIONS,
        _BUGS_UNSUPPRESS_PATH: BUGS_UNSUPPRESS,
    }.get(command_path)
    if command is None or command.auth is None:
        raise ValueError(f"Missing command authorization for {command_path}.")
    return command.auth


def _resolve_project_slug(project_name: str | None, command_path: str) -> str:
    """Resolve the project slug the suppression ledger is keyed on.

    Mirrors the service's slug derivation (``load_project_node``) so the CLI
    writer and the daemon reader resolve the identical ledger path.
    """
    from teleclaude.services.project_catalog.loaders import (  # noqa: PLC0415 - project lookup belongs to suppression resolution.
        load_project_node,
    )

    if project_name:
        root = _resolve_project_by_name(project_name, command_path)
    else:
        try:
            root = resolve_invocation_roots().require_project_root()
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(1) from exc
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

    from teleclaude.api_models import TodoDumpRequest  # noqa: PLC0415 - deferred command-local dependency.
    from teleclaude.cli.tool_client import tool_api_request  # noqa: PLC0415 - deferred command-local dependency.
    from teleclaude.cli.tool_commands._receipt import (  # noqa: PLC0415 - deferred command-local dependency.
        render_receipt,
    )
    from teleclaude.slug import normalize_slug  # noqa: PLC0415 - deferred command-local dependency.

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
    project_root: Path | str = resolve_invocation_cwd()

    # The interrogation gate: a description without the acknowledgment flag
    # is the designed discovery moment (mirrors the sealed-commit gate's
    # discovery semantics) — serving it is the successful outcome, so this
    # exits 0 and files nothing. The gate verifies the pre-filing decisions
    # were faced, never that the answers are true.
    if description and not approved:
        print(_BUG_FILING_GATE, file=sys.stderr, end="")
        return

    if addressed_computer() is not None:
        # The addressed computer resolves the project it holds and refuses by name when it holds none.
        project_root = project_name or project_reference()
    elif project_name:
        project_root = _resolve_project_by_name(project_name, _BUGS_REPORT_PATH)

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
        kind=TodoKind.BUG,
        cwd=str(project_root),
        human_involved=human_involvement_reason is not None,
        human_involvement_reason=human_involvement_reason,
        client_request_id=str(uuid.uuid4()),
    )
    render_receipt(
        tool_api_request(HTTPMethod.POST, _BUG_FILING_PATH, json_body=bug_request.model_dump(mode=_JSON_DUMP_MODE))
    )


def _handle_bugs_list(args: list[str]) -> None:
    """Handle telec bugs list."""
    parsed = parse_command_args(BUGS_LIST, args)
    if parsed.positionals:
        print(f"Unexpected argument: {parsed.positionals[0]}")
        print(_usage("bugs", "list"))
        raise SystemExit(1)

    async def read_bugs(_todos_db: WorkflowStore) -> list[BugListEntryDTO]:
        from teleclaude.services.work import get_work_service  # noqa: PLC0415 - deferred command-local dependency.

        project_root = resolve_invocation_roots().require_project_root()
        return get_work_service(str(project_root)).todo.bug_entries()

    bugs = _read_remote_bugs() if addressed_computer() is not None else run_todo_read(read_bugs)

    if not bugs:
        print("No bugs found")
        return

    print(f"Bug fixes ({len(bugs)}):\n")
    print(f"{'Slug':<40} {'Status':<15}")
    print("-" * 60)
    for bug in bugs:
        print(f"{bug.slug:<40} {bug.status:<15}")


def _read_remote_bugs() -> list[BugListEntryDTO]:
    """The addressed computer's active bugs for the project this invocation acts on."""
    from teleclaude.api_models import BugListEntryDTO  # noqa: PLC0415 - deferred command-local dependency.
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - deferred command-local dependency.

    answer = tool_api_call("GET", _BUGS_PATH, params={"cwd": project_reference()})
    if not isinstance(answer, list):
        raise ValueError(_UNEXPECTED_RESPONSE.format(answer=answer))
    return [BugListEntryDTO.model_validate(row) for row in answer]


def _suppression_scope(project_name: str | None) -> dict[str, str]:
    """Name the project a suppression request is about: the one asked for, else the invoking checkout's."""
    return {"project": project_name} if project_name else {"cwd": project_reference()}


def _remote_suppress(
    project_name: str | None,
    pattern: str,
    match: MatchMode,
    disposition: Disposition,
    reason: str,
    source_bug: str | None,
    expires_at: str | None,
) -> None:
    """Register a suppression in the addressed computer's ledger for the project."""
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - deferred command-local dependency.

    body: dict[str, object] = {  # guard: loose-dict - JSON request body
        "pattern": pattern,
        "match": match.value,
        "disposition": disposition.value,
        "reason": reason,
        "source_bug": source_bug,
        "expires_at": expires_at,
        **_suppression_scope(project_name),
    }
    answer = tool_api_call("POST", _SUPPRESSIONS_PATH, json_body=body)
    if not isinstance(answer, dict):
        raise ValueError(_UNEXPECTED_RESPONSE.format(answer=answer))
    print(f"Registered suppression {answer['id']} for project '{answer['project']}' ({match.value}: {pattern!r}).")


def _remote_suppressions(project_name: str | None) -> tuple[str, list[Suppression]]:
    """The addressed computer's active suppressions for the project."""
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - deferred command-local dependency.

    answer = tool_api_call("GET", _SUPPRESSIONS_PATH, params=_suppression_scope(project_name))
    if not isinstance(answer, dict):
        raise ValueError(_UNEXPECTED_RESPONSE.format(answer=answer))
    entries = [Suppression.from_dict(entry) for entry in answer["suppressions"]]
    return str(answer["project"]), entries


def _remote_unsuppress(project_name: str | None, suppression_id: str) -> tuple[str, bool]:
    """Remove one suppression from the addressed computer's ledger for the project."""
    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - deferred command-local dependency.

    answer = tool_api_call("DELETE", f"{_SUPPRESSIONS_PATH}/{suppression_id}", params=_suppression_scope(project_name))
    if not isinstance(answer, dict):
        raise ValueError(_UNEXPECTED_RESPONSE.format(answer=answer))
    return str(answer["project"]), bool(answer["removed"])


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
    if addressed_computer() is not None:
        _remote_suppress(
            project_name,
            pattern,
            match,
            disposition,
            reason,
            source_bug,
            expires_at.isoformat() if expires_at else None,
        )
        return
    slug = _resolve_project_slug(project_name, _BUGS_SUPPRESS_PATH)
    identity = resolve_cli_identity()
    principal = identity.principal
    if isinstance(identity.caller, NoIdentityCliCaller) or not principal:
        print(no_identity_refusal(identity))
        raise SystemExit(1)

    entry = new_suppression(
        pattern=pattern,
        match=match,
        disposition=disposition,
        reason=reason,
        source_bug=source_bug,
        created_by=principal,
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

    if addressed_computer() is not None:
        slug, entries = _remote_suppressions(project_name)
    else:
        slug = _resolve_project_slug(project_name, _BUGS_SUPPRESSIONS_PATH)
        entries = active(load(suppressions_path_for(slug)), datetime.now(UTC))
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

    if addressed_computer() is not None:
        slug, removed = _remote_unsuppress(project_name, suppression_id)
    else:
        slug = _resolve_project_slug(project_name, _BUGS_UNSUPPRESS_PATH)
        removed = remove(suppressions_path_for(slug), suppression_id)
    if removed:
        print(f"Removed suppression {suppression_id} from project '{slug}'.")
    else:
        print(f"No suppression with id '{suppression_id}' for project '{slug}'.")
        raise SystemExit(1)
