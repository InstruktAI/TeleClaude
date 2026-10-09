"""The telec gate: resolve the role object a command acts on and clear the caller for it.

Only a real command reaches this module; help, usage and completion never load identity or configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

from teleclaude.caller_identity import Company, Person, Platform, Project, ProjectPath, RelayedAct, RoleTarget
from teleclaude.cli import CommandScope, ConfigSubjectType
from teleclaude.cli.session_auth import ComputerTargetDisposition, classify_computer_target, require_cli_clearance
from teleclaude.cli.telec.handlers._arg_parsing import ParsedArgs
from teleclaude.cli.telec.router import CommandClearance
from teleclaude.cli.telec.surface import CommandAuth, CommandDef
from teleclaude.config.errors import ConfigLoadError, describe_load_error
from teleclaude.paths import invocation_cwd
from teleclaude.slug import normalize_slug

_CONFIGURATION_UNREADABLE_ERROR = "Error: {error}"
_RELAYED_ACT_PATHS = frozenset(act.value.removeprefix("telec ") for act in RelayedAct)


def clear_command(request: CommandClearance) -> None:
    """Clear the caller for one parsed command, or print why not and exit non-zero."""
    try:
        role_target = _role_target_for_command(
            request.path,
            request.node,
            request.auth,
            request.parsed,
            request.target_computer,
            request.direct_conversation,
        )
        require_cli_clearance(
            " ".join(request.path),
            request.target_session_id,
            request.auth,
            role_target=role_target,
            target_computer=request.target_computer,
            direct_conversation=request.direct_conversation,
            desk_command=request.node.desk,
        )
    except ConfigLoadError as exc:
        print(_CONFIGURATION_UNREADABLE_ERROR.format(error=describe_load_error(exc)), file=sys.stderr)
        raise SystemExit(1) from exc
    except FileNotFoundError as exc:
        print(_CONFIGURATION_UNREADABLE_ERROR.format(error=exc), file=sys.stderr)
        raise SystemExit(1) from exc


def _role_target_for_command(
    path: list[str],
    node: CommandDef,
    auth: CommandAuth | None,
    parsed: ParsedArgs,
    target_computer: str | None,
    direct_conversation: bool,
) -> RoleTarget | None:
    """Resolve the declared person-role object from the parsed command target."""
    if auth is None or auth.caller_independent:
        return None
    if classify_computer_target(target_computer) is ComputerTargetDisposition.REMOTE:
        if " ".join(path) in _RELAYED_ACT_PATHS:
            return Platform() if direct_conversation else None
        return Platform()
    if auth.scope is CommandScope.PLATFORM:
        return Platform()
    if auth.scope is CommandScope.CONFIG_SUBJECT:
        if len(path) < 2 or not parsed.positionals:
            return Platform()
        try:
            subject_type = ConfigSubjectType(path[1])
        except ValueError:
            return Platform()
        subject = parsed.positionals[0]
        if subject_type is ConfigSubjectType.PERSON:
            return Person(subject)
        if subject_type is ConfigSubjectType.COMPANY:
            return Company(subject)
        return Project(subject)
    if auth.scope in (CommandScope.TARGET_SESSION, CommandScope.CALLER_PERSON):
        return None
    if auth.scope is CommandScope.NAMED_COMPANY:
        return _named_company_target(node, auth, parsed)
    if auth.scope is CommandScope.NAMED_TRUSTED_DIRECTORY:
        if auth.scope_flag is None:
            return Platform()
        flag = next((candidate for candidate in node.flags if candidate.long == auth.scope_flag), None)
        if flag is None:
            return Platform()
        if parsed.value(flag) is None:
            return ProjectPath(invocation_cwd())
        return None
    if auth.scope is CommandScope.TARGET_PATH:
        target_value: str | None = None
        if auth.scope_flag is not None:
            flag = next((candidate for candidate in node.flags if candidate.long == auth.scope_flag), None)
            if flag is not None:
                target_value = parsed.value(flag)
        if target_value is None:
            return ProjectPath(invocation_cwd())
        return ProjectPath(Path(target_value).expanduser())
    return ProjectPath(invocation_cwd())


def _named_company_target(node: CommandDef, auth: CommandAuth, parsed: ParsedArgs) -> RoleTarget:
    """Resolve the company a command names: its scope flag's value, else its normalized first positional."""
    flag = next((candidate for candidate in node.flags if candidate.long == auth.scope_flag), None)
    named = parsed.value(flag) if flag is not None else None
    if named is None and parsed.positionals:
        named = normalize_slug(parsed.positionals[0])
    return Company(named.strip()) if named and named.strip() else Platform()
