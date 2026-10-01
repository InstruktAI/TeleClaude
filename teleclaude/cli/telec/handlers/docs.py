"""Handlers for telec docs commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.cli.session_auth import resolve_cli_caller
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import DOCS_GET, DOCS_INDEX
from teleclaude.config.loader import load_app_config
from teleclaude.config.schema import ConfigKind
from teleclaude.context_selector import ActivationClosureError, build_context_output
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.snippet_scope import SnippetScope

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
    landing_kind: ConfigKind | None


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
    """Resolve the landed home; the landing sets only the default read set."""
    roots = resolve_invocation_roots()
    if roots.context_root is None:
        return DocsContext(project_root=roots.invocation_dir, landing_kind=None)
    if roots.context_kind is ConfigKind.PROJECT:
        return DocsContext(project_root=roots.require_project_root(), landing_kind=ConfigKind.PROJECT)
    return DocsContext(project_root=roots.context_root, landing_kind=roots.context_kind)


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
    from teleclaude.domains import valid_domains  # noqa: PLC0415 - deferred command-local dependency.

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
    parsed = parse_command_args(DOCS_INDEX, args)
    if parsed.positionals:
        print(f"Unexpected positional argument for docs index: {parsed.positionals[0]}")
        print(_usage("docs", "index"))
        raise SystemExit(1)

    baseline_only = parsed.has(F.FLAG_DOCS_BASELINE_ONLY)
    third_party = parsed.has(F.FLAG_DOCS_THIRD_PARTY)
    areas_raw = parsed.value(F.FLAG_DOCS_AREAS)
    areas = [a.strip() for a in areas_raw.split(",") if a.strip()] if areas_raw is not None else []
    domains_raw = parsed.value(F.FLAG_DOCS_DOMAINS)
    domains = _parse_domains(domains_raw, "index") if domains_raw is not None else None
    scope_raw = parsed.value(F.FLAG_DOCS_SCOPE)
    scope = _parse_scope(scope_raw.strip(), "index") if scope_raw is not None else None
    project_raw = parsed.value(F.FLAG_DOCS_PROJECT)
    projects = [project_raw.strip().lower()] if project_raw is not None else None
    person_raw = parsed.value(F.FLAG_DOCS_PERSON)
    person = person_raw.strip().lower() if person_raw is not None else None
    company_raw = parsed.value(F.FLAG_DOCS_COMPANY)
    company = company_raw.strip().lower() if company_raw is not None else None
    target_raw = parsed.value(F.FLAG_DOCS_TARGET)
    target_slug = target_raw.strip() if target_raw is not None else None

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
    caller = resolve_cli_caller()
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
        person=person,
        company=company,
        caller=caller,
        config=config,
        landing_kind=docs_context.landing_kind,
        retrieval_id=context.retrieval_id,
        verb=context.verb.value,
    )
    print(output)


def _handle_docs_get(args: list[str], context: DocsRetrievalContext) -> None:
    """Handle telec docs get."""
    parsed = parse_command_args(DOCS_GET, args)
    snippet_ids: list[str] = []
    for token in parsed.positionals:
        for part in token.split(","):
            part = part.strip()
            if part:
                snippet_ids.append(part)

    if not snippet_ids:
        print("At least one snippet ID is required.")
        print(_usage("docs", "get"))
        raise SystemExit(1)

    closure = parsed.has(F.FLAG_DOCS_GET_CLOSURE)
    target_raw = parsed.value(F.FLAG_DOCS_GET_TARGET)
    target_slug = target_raw.strip() if target_raw is not None else None
    scope_raw = parsed.value(F.FLAG_DOCS_SCOPE)
    scope = _parse_scope(scope_raw.strip(), "get") if scope_raw is not None else None
    project_raw = parsed.value(F.FLAG_DOCS_PROJECT)
    projects = [project_raw.strip().lower()] if project_raw is not None else None
    person_raw = parsed.value(F.FLAG_DOCS_PERSON)
    person = person_raw.strip().lower() if person_raw is not None else None
    company_raw = parsed.value(F.FLAG_DOCS_COMPANY)
    company = company_raw.strip().lower() if company_raw is not None else None

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
    caller = resolve_cli_caller()
    config = load_app_config(docs_context.project_root)
    try:
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
            person=person,
            company=company,
            closure=closure,
            caller=caller,
            config=config,
            landing_kind=docs_context.landing_kind,
            retrieval_id=context.retrieval_id,
            verb=context.verb.value,
        )
    except ActivationClosureError as error:
        print(error)
        raise SystemExit(1) from error
    print(output)


_DOCS_HANDLERS: dict[DocsVerb, DocsHandler] = {
    DocsVerb.INDEX: _handle_docs_index,
    DocsVerb.GET: _handle_docs_get,
}
