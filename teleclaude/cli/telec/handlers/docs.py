"""Handlers for telec docs commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.cli.telec.help import _usage
from teleclaude.config.context_root import resolve_context_root
from teleclaude.config.loader import load_app_config
from teleclaude.config.schema import ConfigKind
from teleclaude.context_selector import build_context_output
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.domains import valid_domains
from teleclaude.project_root import (
    resolve_invocation_cwd,
)
from teleclaude.snippet_validation import SnippetScope

__all__ = [
    "_handle_docs",
    "_handle_docs_get",
    "_handle_docs_index",
]

logger = get_logger(__name__)


class DocsRetrievalEvent(StrEnum):
    REQUESTED = "docs_retrieval_requested"
    ACCEPTED = "docs_retrieval_accepted"
    COMPLETED = "docs_retrieval_completed"


class DocsRetrievalOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class DocsRetrievalReason(StrEnum):
    INVALID_ARGUMENTS = "invalid_arguments"
    OPERATION_ERROR = "operation_error"


class DocsVerb(StrEnum):
    INDEX = "index"
    GET = "get"


@dataclass(frozen=True)
class DocsRetrievalContext:
    retrieval_id: str
    verb: DocsVerb


@dataclass(frozen=True)
class DocsContext:
    project_root: Path
    include_registered_projects: bool


DocsHandler = Callable[[list[str], DocsRetrievalContext], None]


def _emit_retrieval_accepted(
    context: DocsRetrievalContext,
    *,
    default_index: bool,
    explicit_project_filter: bool,
    target_filter: bool,
    scope_filter: bool,
    area_filter: bool,
    domain_filter: bool,
    requested_id_count: int,
    third_party_requested: bool,
) -> None:
    logger.info(
        DocsRetrievalEvent.ACCEPTED.value,
        retrieval_id=context.retrieval_id,
        verb=context.verb.value,
        default_index=default_index,
        explicit_project_filter=explicit_project_filter,
        target_filter=target_filter,
        scope_filter=scope_filter,
        area_filter=area_filter,
        domain_filter=domain_filter,
        requested_id_count=requested_id_count,
        third_party_requested=third_party_requested,
    )


def _resolve_docs_context() -> DocsContext:
    invocation_cwd = resolve_invocation_cwd()
    context = resolve_context_root(invocation_cwd)
    if context is None:
        return DocsContext(project_root=invocation_cwd, include_registered_projects=True)
    if context.kind is ConfigKind.PROJECT:
        return DocsContext(project_root=resolve_project_state_root(context.path), include_registered_projects=False)
    return DocsContext(project_root=context.path, include_registered_projects=False)


def _current_terminal_role() -> str | None:
    email = read_current_session_email()
    if not email:
        return None
    return get_identity_resolver().resolve_by_email(email).person_role


def _parse_scope(value: str, subcommand: str) -> SnippetScope:
    """Parse a ``--scope`` value into ``SnippetScope`` or fail fast."""
    try:
        return SnippetScope(value)
    except ValueError:
        valid = ", ".join(member.value for member in SnippetScope)
        print(f"Invalid --scope value: {value}. Valid values: {valid}.")
        print(_usage("docs", subcommand))
        raise SystemExit(1) from None


def _parse_domains(value: str, subcommand: str) -> list[str]:
    """Parse a ``--domains`` value against the published-domain set or fail fast.

    Valid domains are exactly the published-domain union (``valid_domains()``);
    structural scopes like ``general``/``project`` are not selectable here, mirroring
    the phase-1 header's advertised choices.
    """
    requested = [d.strip() for d in value.split(",") if d.strip()]
    if not requested:
        # An empty/whitespace/comma-only value supplies no domain; treat it as a
        # missing value rather than silently degrading to an unfiltered listing.
        print("Missing value for --domains.")
        print(_usage("docs", subcommand))
        raise SystemExit(1)
    valid = valid_domains()
    invalid = [d for d in requested if d not in valid]
    if invalid:
        valid_list = ", ".join(sorted(valid)) or "(none registered)"
        print(f"Invalid --domains value(s): {', '.join(invalid)}. Valid domains: {valid_list}.")
        print(_usage("docs", subcommand))
        raise SystemExit(1)
    return requested


def _handle_docs(args: list[str]) -> None:
    """Handle telec docs commands."""
    if not args:
        print(_usage("docs"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("docs"))
        return

    try:
        verb = DocsVerb(args[0])
    except ValueError:
        subcommand = args[0]
        print(f"Unknown docs subcommand: {subcommand}")
        print(_usage("docs"))
        raise SystemExit(1)
    context = DocsRetrievalContext(retrieval_id=str(uuid4()), verb=verb)
    logger.info(DocsRetrievalEvent.REQUESTED.value, retrieval_id=context.retrieval_id, verb=context.verb.value)
    handler = _DOCS_HANDLERS[verb]
    try:
        handler(args[1:], context)
    except SystemExit:
        logger.info(
            DocsRetrievalEvent.COMPLETED.value,
            retrieval_id=context.retrieval_id,
            verb=context.verb.value,
            outcome=DocsRetrievalOutcome.REJECTED.value,
            reason=DocsRetrievalReason.INVALID_ARGUMENTS.value,
        )
        raise
    except Exception:
        logger.info(
            DocsRetrievalEvent.COMPLETED.value,
            retrieval_id=context.retrieval_id,
            verb=context.verb.value,
            outcome=DocsRetrievalOutcome.FAILED.value,
            reason=DocsRetrievalReason.OPERATION_ERROR.value,
        )
        raise
    logger.info(
        DocsRetrievalEvent.COMPLETED.value,
        retrieval_id=context.retrieval_id,
        verb=context.verb.value,
        outcome=DocsRetrievalOutcome.SUCCEEDED.value,
    )


def _handle_docs_index(args: list[str], context: DocsRetrievalContext) -> None:
    """Handle telec docs index."""
    baseline_only = False
    third_party = False
    areas: list[str] = []
    domains: list[str] | None = None
    target_slug: str | None = None
    scope: SnippetScope | None = None
    projects: list[str] | None = None

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
            domains = _parse_domains(args[i + 1], "index")
            i += 2
        elif arg in ("--domains", "-d"):
            print("Missing value for --domains.")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        elif arg == "--scope" and i + 1 < len(args):
            scope = _parse_scope(args[i + 1].strip(), "index")
            i += 2
        elif arg == "--scope":
            print("Missing value for --scope.")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        elif arg == "--project" and i + 1 < len(args):
            projects = [args[i + 1].strip().lower()]
            i += 2
        elif arg == "--project":
            print("Missing value for --project.")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        elif arg == "--target" and i + 1 < len(args):
            target_slug = args[i + 1].strip()
            i += 2
        elif arg == "--target":
            print("Missing value for --target.")
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

    _emit_retrieval_accepted(
        context,
        default_index=not any((areas, domains, target_slug, scope, projects, baseline_only, third_party)),
        explicit_project_filter=projects is not None,
        target_filter=target_slug is not None,
        scope_filter=scope is not None,
        area_filter=bool(areas),
        domain_filter=domains is not None,
        requested_id_count=0,
        third_party_requested=third_party,
    )
    docs_context = _resolve_docs_context()
    effective_role = _current_terminal_role()
    config = load_app_config(docs_context.project_root)
    output = build_context_output(
        areas=areas,
        project_root=docs_context.project_root,
        snippet_ids=None,
        baseline_only=baseline_only,
        include_third_party=third_party,
        domains=domains,
        target_slug=target_slug,
        scope=scope,
        projects=projects,
        effective_human_role=effective_role,
        config=config,
        include_registered_projects=docs_context.include_registered_projects,
        retrieval_id=context.retrieval_id,
        verb=context.verb.value,
    )
    print(output)


def _handle_docs_get(args: list[str], context: DocsRetrievalContext) -> None:
    """Handle telec docs get."""
    snippet_ids: list[str] = []
    target_slug: str | None = None
    scope: SnippetScope | None = None
    projects: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--target" and i + 1 < len(args):
            target_slug = args[i + 1].strip()
            i += 2
            continue
        if arg == "--target":
            print("Missing value for --target.")
            print(_usage("docs", "get"))
            raise SystemExit(1)
        if arg == "--scope" and i + 1 < len(args):
            scope = _parse_scope(args[i + 1].strip(), "get")
            i += 2
            continue
        if arg == "--scope":
            print("Missing value for --scope.")
            print(_usage("docs", "get"))
            raise SystemExit(1)
        if arg == "--project" and i + 1 < len(args):
            projects = [args[i + 1].strip().lower()]
            i += 2
            continue
        if arg == "--project":
            print("Missing value for --project.")
            print(_usage("docs", "get"))
            raise SystemExit(1)
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

    _emit_retrieval_accepted(
        context,
        default_index=False,
        explicit_project_filter=projects is not None,
        target_filter=target_slug is not None,
        scope_filter=scope is not None,
        area_filter=False,
        domain_filter=False,
        requested_id_count=len(snippet_ids),
        third_party_requested=False,
    )
    docs_context = _resolve_docs_context()
    effective_role = _current_terminal_role()
    config = load_app_config(docs_context.project_root)
    output = build_context_output(
        areas=[],
        project_root=docs_context.project_root,
        snippet_ids=snippet_ids,
        baseline_only=False,
        include_third_party=False,
        domains=None,
        target_slug=target_slug,
        scope=scope,
        projects=projects,
        effective_human_role=effective_role,
        config=config,
        include_registered_projects=docs_context.include_registered_projects,
        retrieval_id=context.retrieval_id,
        verb=context.verb.value,
    )
    print(output)


_DOCS_HANDLERS: dict[DocsVerb, DocsHandler] = {
    DocsVerb.INDEX: _handle_docs_index,
    DocsVerb.GET: _handle_docs_get,
}
