"""Managed agent-runtime ingress for the Google connector boundary."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from teleclaude.config.context_root import resolve_context_root
from teleclaude.config.loader import load_person_config
from teleclaude.config.schema import ConfigKind
from teleclaude.core.identity import (
    AcceptedPersonContextBinding,
    PersonContextBindingRefusal,
    PersonContextBindingRegistryError,
    RefusedPersonContextBinding,
    get_identity_resolver,
)
from teleclaude.core.integration.assistant_connector import (
    AssistantConnectorDecision,
    AssistantConnectorOutcome,
    AssistantConnectorRefusalReason,
    GoogleConnectorLaunchContext,
    prepare_assistant_connector_invocation,
    refuse_assistant_connector_invocation,
)
from teleclaude.paths import BIN_DIR, ConfigFileName
from teleclaude.project_root import resolve_invocation_cwd

_ACCOUNT_FLAG = "--account"
_SHORT_ACCOUNT_FLAG = "-a"
_ACCOUNT_ASSIGNMENT_PREFIX = "--account="
_HELP_FLAGS = frozenset({"--help", "-h"})
_VERSION_ARGUMENTS = ("--version",)
_USAGE = "usage: gog --account <declared-address> <command> [arguments]"
_REFUSAL_PREFIX = "assistant connector refused: "
_GOOGLE_BINARY_NAME = "gog"
_GOOGLE_HOME_ENV = "GOG_HOME"
_GOOGLE_ACCOUNT_ENV = "GOG_ACCOUNT"
_GOOGLE_ACCESS_TOKEN_ENV = "GOG_ACCESS_TOKEN"
_GOOGLE_AUTH_MODE_ENV = "GOG_AUTH_MODE"
_GOOGLE_CONFIG_ENV = "GOG_CONFIG_DIR"
_GOOGLE_DATA_ENV = "GOG_DATA_DIR"
_GOOGLE_STATE_ENV = "GOG_STATE_DIR"
_GOOGLE_CACHE_ENV = "GOG_CACHE_DIR"
_PATH_ENV = "PATH"
_GOOGLE_CONTROL_ENVIRONMENT = frozenset(
    {
        _GOOGLE_HOME_ENV,
        _GOOGLE_ACCOUNT_ENV,
        _GOOGLE_ACCESS_TOKEN_ENV,
        _GOOGLE_AUTH_MODE_ENV,
        _GOOGLE_CONFIG_ENV,
        _GOOGLE_DATA_ENV,
        _GOOGLE_STATE_ENV,
        _GOOGLE_CACHE_ENV,
    }
)

_BINDING_REFUSAL_REASONS = {
    PersonContextBindingRefusal.UNKNOWN: AssistantConnectorRefusalReason.PERSON_BINDING_UNKNOWN,
    PersonContextBindingRefusal.AMBIGUOUS: AssistantConnectorRefusalReason.PERSON_BINDING_AMBIGUOUS,
    PersonContextBindingRefusal.DISAGREEING: AssistantConnectorRefusalReason.PERSON_BINDING_DISAGREEING,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Serve help, resolve version metadata without person ingress, or replace this process with an admitted connector."""
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if _HELP_FLAGS.intersection(arguments):
        print(_USAGE)
        return 0
    if arguments == _VERSION_ARGUMENTS:
        launch_context = _resolve_google_launch_context()
        if isinstance(launch_context, AssistantConnectorDecision):
            return _report_refusal(launch_context)
        # gog is an external binary with no Python binding; process replacement preserves its version output and exit code.
        os.execve(
            str(launch_context.binary),
            (str(launch_context.binary), *_VERSION_ARGUMENTS),
            launch_context.environment,
        )
        return 0
    account_address, connector_arguments = _extract_account(arguments)
    binding = _resolve_person_binding(resolve_invocation_cwd())
    if isinstance(binding, AssistantConnectorDecision):
        return _report_refusal(binding)
    launch_context = _resolve_google_launch_context()
    if isinstance(launch_context, AssistantConnectorDecision):
        return _report_refusal(launch_context)
    decision = prepare_assistant_connector_invocation(binding, account_address, connector_arguments, launch_context)
    if decision.outcome is AssistantConnectorOutcome.REFUSED:
        return _report_refusal(decision)
    process = decision.process
    if process is None:
        return _report_refusal(
            refuse_assistant_connector_invocation(AssistantConnectorRefusalReason.BINARY_UNAVAILABLE)
        )
    # gog is an external binary with no Python binding; replacing the process preserves its exit code and I/O.
    os.execve(process.command[0], process.command, process.environment)
    return 0


def _extract_account(arguments: Sequence[str]) -> tuple[str | None, tuple[str, ...]]:
    """Separate the named account from the connector vector without interpreting commands."""
    account_address: str | None = None
    connector_arguments: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {_ACCOUNT_FLAG, _SHORT_ACCOUNT_FLAG}:
            index += 1
            if index < len(arguments) and account_address is None:
                account_address = arguments[index]
            elif index < len(arguments):
                connector_arguments.extend((argument, arguments[index]))
        elif argument.startswith(_ACCOUNT_ASSIGNMENT_PREFIX) and account_address is None:
            account_address = argument.removeprefix(_ACCOUNT_ASSIGNMENT_PREFIX)
        else:
            connector_arguments.append(argument)
        index += 1
    return account_address, tuple(connector_arguments)


def _resolve_person_binding(invocation_cwd: Path) -> AcceptedPersonContextBinding | AssistantConnectorDecision:
    """Produce the validated workspace-person binding required by the boundary."""
    try:
        context = resolve_context_root(invocation_cwd)
    except (OSError, ValueError):
        return refuse_assistant_connector_invocation(
            AssistantConnectorRefusalReason.PERSON_CONTEXT_DECLARATION_UNREADABLE
        )
    if context is None:
        return refuse_assistant_connector_invocation(AssistantConnectorRefusalReason.PERSON_CONTEXT_MISSING)
    if context.kind is not ConfigKind.PERSON:
        return refuse_assistant_connector_invocation(AssistantConnectorRefusalReason.PERSON_CONTEXT_NOT_PERSON)
    try:
        person_config = load_person_config(context.path / ConfigFileName.OVERLAY)
    except (OSError, ValueError):
        return refuse_assistant_connector_invocation(
            AssistantConnectorRefusalReason.PERSON_CONTEXT_DECLARATION_UNREADABLE
        )
    try:
        binding = get_identity_resolver().resolve_person_context_binding(person_config.slug, context.path)
    except PersonContextBindingRegistryError:
        return refuse_assistant_connector_invocation(
            AssistantConnectorRefusalReason.PERSON_BINDING_REGISTRY_UNAVAILABLE
        )
    if isinstance(binding, RefusedPersonContextBinding):
        return refuse_assistant_connector_invocation(_BINDING_REFUSAL_REASONS[binding.refusal])
    return binding


def _resolve_google_launch_context() -> GoogleConnectorLaunchContext | AssistantConnectorDecision:
    """Inject the only executable and environment the integration boundary may use."""
    environment = {
        key: value
        for key, value in os.environ.items()  # guard: direct-env-read - child-process startup seam
        if key not in _GOOGLE_CONTROL_ENVIRONMENT
    }
    wrapper_path = (BIN_DIR / _GOOGLE_BINARY_NAME).resolve()
    search_path = environment.get(_PATH_ENV, os.defpath)
    for directory in search_path.split(os.pathsep):
        candidate = (Path(directory) / _GOOGLE_BINARY_NAME).resolve()
        if candidate == wrapper_path:
            continue
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return GoogleConnectorLaunchContext(binary=candidate, environment=environment)
    return refuse_assistant_connector_invocation(AssistantConnectorRefusalReason.BINARY_UNAVAILABLE)


def _report_refusal(decision: AssistantConnectorDecision) -> int:
    """Emit only the closed refusal reason and return a command-failure exit code."""
    reason = (
        decision.reason.value
        if decision.reason is not None
        else AssistantConnectorRefusalReason.BINARY_UNAVAILABLE.value
    )
    print(_REFUSAL_PREFIX + reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
