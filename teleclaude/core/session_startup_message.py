"""Core-owned startup-message preparation after agent selection."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from teleclaude.constants import SlashCommand
from teleclaude.core.command_input import (
    CommandInputError,
    CommandInputMode,
    CommandInputResult,
    NoCommandInput,
    RefusedCommandInput,
    ResolvedCommandInput,
    normalize_command_input_token,
)
from teleclaude.paths import COMMANDS_DIR

_COMMAND_PREFIX = "/"
_COMMAND_FILE_SUFFIX = ".md"
_COMMANDS_ROOT = COMMANDS_DIR.resolve()
_COMMAND_MARKER_TEMPLATE = "TELECLAUDE COMMAND: {command}{args}"
_MARKER_ARGUMENT_PREFIX = " "
_LOADER_SECTION_SEPARATOR = "\n\n"
_LINE_SEPARATOR = "\n"
_COMMAND_ARGUMENT_SEPARATOR = " "
_QUALIFIED_NAME_SEPARATOR = "/"
_TRAVERSAL_SEGMENTS = frozenset({".", ".."})
_LOADER_MESSAGE_TEMPLATE = (
    "Read {prompt_path} verbatim and follow it exactly as the active instruction set for this session.\n\n"
    "Treat the following as provided inputs to that instruction set:\n"
    "{args}"
)
_UNKNOWN_COMMAND_MESSAGE_TEMPLATE = "/{command} resolves to no installed command document"
_AMBIGUOUS_COMMAND_MESSAGE_TEMPLATE = "/{command} matches more than one global domain: {candidates}"


class StartupMessageError(ValueError):
    """A startup message violates the selected runtime's contract."""


class AmbiguousCommandError(StartupMessageError):
    """A bare command token matched more than one domain in the global corpus."""


class ResolvedCommand(NamedTuple):
    """A command name resolved to its one canonical, installed document.

    ``canonical_name`` is the value every downstream consumer — role/job
    inference, session title, session record, dedup, and the loader marker —
    reads instead of re-deriving its own notion of "the command".
    """

    canonical_name: str
    document: Path


def _is_safe_segment(segment: str) -> bool:
    return bool(segment) and segment not in _TRAVERSAL_SEGMENTS and _COMMAND_PREFIX not in segment


def _resolve_qualified(domain: str, name: str) -> ResolvedCommand | None:
    if not _is_safe_segment(domain) or not _is_safe_segment(name):
        return None
    candidate = (COMMANDS_DIR / domain / f"{name}{_COMMAND_FILE_SUFFIX}").resolve()
    if not candidate.is_relative_to(_COMMANDS_ROOT):
        return None
    if not candidate.is_file():
        return None
    return ResolvedCommand(f"{domain}/{name}", candidate)


def _scan_domain_matches(name: str) -> list[tuple[str, Path]]:
    if not _COMMANDS_ROOT.is_dir():
        return []
    matches: list[tuple[str, Path]] = []
    for entry in sorted(_COMMANDS_ROOT.iterdir(), key=lambda path: path.name):
        if not entry.is_dir():
            continue
        candidate = entry / f"{name}{_COMMAND_FILE_SUFFIX}"
        if candidate.is_file():
            matches.append((entry.name, candidate))
    return matches


def resolve_command_document(command_name: str) -> ResolvedCommand | None:
    """Resolve a command name to its one canonical, installed document.

    A domain-qualified name (``<domain>/<name>``) resolves directly. A bare
    token scans every domain directory in the global corpus for a same-named
    file: a single domain match is canonicalized to ``<domain>/<name>``; the
    transitional flat root file is the fallback only when no domain match
    exists; more than one domain match raises rather than silently picking
    one candidate.
    """
    segments = command_name.split(_QUALIFIED_NAME_SEPARATOR)
    if len(segments) == 2:
        return _resolve_qualified(*segments)
    if len(segments) != 1 or not _is_safe_segment(segments[0]):
        return None
    name = segments[0]
    domain_matches = _scan_domain_matches(name)
    if len(domain_matches) > 1:
        candidates = ", ".join(f"{domain}/{name}" for domain, _ in domain_matches)
        raise AmbiguousCommandError(_AMBIGUOUS_COMMAND_MESSAGE_TEMPLATE.format(command=name, candidates=candidates))
    if len(domain_matches) == 1:
        domain, document = domain_matches[0]
        return ResolvedCommand(f"{domain}/{name}", document)
    legacy_document = (COMMANDS_DIR / f"{name}{_COMMAND_FILE_SUFFIX}").resolve()
    if not legacy_document.is_relative_to(_COMMANDS_ROOT) or not legacy_document.is_file():
        return None
    return ResolvedCommand(name, legacy_document)


def resolve_slash_command(command: str | None) -> SlashCommand | None:
    """Resolve a possibly slash-prefixed, possibly bare token to its `SlashCommand` member.

    The single canonicalizing seam behind every ``SlashCommand(...)`` lookup
    that starts from a caller-, message-, or database-supplied string rather
    than an already-typed enum value: a bare token (as typed by a human, held
    by a session predating the qualification migration, or read from stored
    dispatch state) is resolved against the global corpus first, so it still
    matches its qualified member. An ambiguous bare token resolves to no
    member here — the dispatch boundary that first saw the raw string is
    where ambiguity is refused; this helper only classifies.
    """
    if command is None:
        return None
    bare = command.lstrip(_COMMAND_PREFIX)
    try:
        resolved = resolve_command_document(bare)
    except AmbiguousCommandError:
        resolved = None
    canonical = resolved.canonical_name if resolved is not None else bare
    try:
        return SlashCommand(canonical)
    except ValueError:
        return None


def compose_command_loader(
    command_name: str,
    args: str,
) -> str:
    """Compose the loader for an already-resolved command name and its arguments.

    Raises when the command resolves to no installed document, or when a
    bare token is ambiguous across domains. Argument admissibility is the
    caller's rule, not this function's — it parses nothing and gates nothing
    but document existence and uniqueness. The marker and loader both use
    the resolved canonical name, never the name as given.
    """
    resolved = resolve_command_document(command_name)
    if resolved is None:
        raise StartupMessageError(_UNKNOWN_COMMAND_MESSAGE_TEMPLATE.format(command=command_name))
    marker_args = f"{_MARKER_ARGUMENT_PREFIX}{args}" if args else ""
    return _LOADER_SECTION_SEPARATOR.join(
        section
        for section in (
            _COMMAND_MARKER_TEMPLATE.format(command=resolved.canonical_name, args=marker_args),
            _LOADER_MESSAGE_TEMPLATE.format(prompt_path=resolved.document, args=args),
        )
        if section
    )


def resolve_command_input(message: str | None, mode: CommandInputMode) -> CommandInputResult:
    """Resolve opt-in interactive shorthand without changing ordinary chat parsing."""
    if mode is CommandInputMode.ORDINARY or not message:
        return NoCommandInput()
    first_line = message.partition(_LINE_SEPARATOR)[0]
    command_token, _, raw_args = first_line.partition(_COMMAND_ARGUMENT_SEPARATOR)
    if not command_token:
        return NoCommandInput()
    try:
        command_name = normalize_command_input_token(command_token)
    except CommandInputError as exc:
        if command_token.startswith(_COMMAND_PREFIX):
            return RefusedCommandInput(detail=str(exc))
        return NoCommandInput()
    try:
        resolved = resolve_command_document(command_name)
    except AmbiguousCommandError as exc:
        return RefusedCommandInput(detail=str(exc))
    if resolved is None:
        return NoCommandInput()
    return ResolvedCommandInput(command=resolved.canonical_name, args=raw_args.strip())


def prepare_startup_message(
    startup_message: str,
    declared_command: str | None,
) -> str:
    """Compose a loader for a dispatched session, from the message's first line only.

    With ``declared_command``, compose from that command and the arguments
    following it on the first line, then re-append everything after the
    first line unchanged; a command that resolves to no installed document
    raises rather than passing the raw text through. With no declared
    command, keep chat's permissive behavior: resolve the first line's
    leading token against the installed command corpus and pass the message
    through unchanged when it does not resolve or is ambiguous.
    """
    stripped_message = startup_message.lstrip()
    first_line, _, trailing = stripped_message.partition("\n")
    trailing = trailing.strip("\n")
    if declared_command is None:
        if not first_line.startswith(_COMMAND_PREFIX):
            return startup_message
        command_token, _, first_line_args = first_line.partition(" ")
        command_name = command_token.removeprefix(_COMMAND_PREFIX)
        if not command_name:
            return startup_message
        try:
            resolved = resolve_command_document(command_name)
        except AmbiguousCommandError:
            return startup_message
        if resolved is None:
            return startup_message
        args = first_line_args.strip()
        composed = compose_command_loader(resolved.canonical_name, args)
    else:
        _, _, first_line_args = first_line.partition(" ")
        args = first_line_args.strip()
        composed = compose_command_loader(declared_command, args)
    if trailing:
        composed = f"{composed}{_LOADER_SECTION_SEPARATOR}{trailing}"
    return composed
