"""Managed-runner credential preflight.

Verifies each canonical agent's credential store is present and readable,
keyed exhaustively by the registry's declared ``CredentialCheckKind`` — a
canonical agent whose check kind this module does not handle fails loudly at
`_CHECK_HANDLERS[check.kind]` rather than being silently skipped. Reports no
credential content, path, or account identity beyond the bare presence
outcome.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AGENT_REGISTRY, AgentName, CredentialCheck, CredentialCheckKind, registry_digest
from teleclaude.core.agents import get_enabled_agents

logger = get_logger(__name__)

AGENT_PREFLIGHT_EVENT = "agent_runtime.agent_preflight"

_LOGIN_KEYCHAIN = Path.home() / "Library" / "Keychains" / "login.keychain-db"

# Display labels for the preflight report only; the registry key remains the
# single source of canonical identity everywhere else.
_DISPLAY_LABEL: dict[AgentName, str] = {
    AgentName.CLAUDE: "Claude",
    AgentName.CODEX: "Codex",
    AgentName.GEMINI: "Antigravity (agy)",
    AgentName.DEEPSEEK: "DeepSeek",
}


class PreflightStage(StrEnum):
    """Closed lifecycle stage for one preflight run."""

    STARTED = "started"
    COMPLETED = "completed"


class PreflightOutcome(StrEnum):
    """Closed outcome for one agent's credential preflight."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class PreflightReason(StrEnum):
    """Closed reason token for one agent's terminal preflight outcome."""

    CREDENTIAL_FOUND = "credential_found"
    CREDENTIAL_NOT_FOUND = "credential_not_found"


@dataclass(frozen=True)
class PreflightResult:
    """One agent's preflight outcome, with no credential content attached."""

    agent: AgentName
    outcome: PreflightOutcome
    login_hint: str


def _keychain_readable(service: str) -> bool:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w", str(_LOGIN_KEYCHAIN)],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _file_present(path: str) -> bool:
    return Path(path).expanduser().is_file()


def _check_keychain_service(check: CredentialCheck) -> bool:
    return any(_keychain_readable(service) for service in check.keychain_services)


def _check_file_presence(check: CredentialCheck) -> bool:
    return _file_present(check.file_path)


def _check_keychain_or_file(check: CredentialCheck) -> bool:
    return _check_keychain_service(check) or _check_file_presence(check)


_CHECK_HANDLERS: dict[CredentialCheckKind, Callable[[CredentialCheck], bool]] = {
    CredentialCheckKind.KEYCHAIN_SERVICE: _check_keychain_service,
    CredentialCheckKind.FILE_PRESENCE: _check_file_presence,
    CredentialCheckKind.KEYCHAIN_OR_FILE: _check_keychain_or_file,
}


def run_preflight(
    agents: Iterable[AgentName] | None = None, *, run_id: str | None = None
) -> tuple[PreflightResult, ...]:
    """Run the credential-presence check for the requested agents (default: every canonical agent).

    Emits the closed ``agent_runtime.agent_preflight`` observation record
    family: one ``started`` record with the registry digest and enabled
    agent count before any runtime-specific check, then exactly one terminal
    ``completed`` record per checked agent. No credential content, path, or
    account identity is ever logged — only the closed outcome/reason tokens.
    """
    resolved_run_id = run_id if run_id is not None else str(uuid4())
    targets = tuple(agents) if agents is not None else tuple(AgentName)
    digest = registry_digest()
    logger.info(
        AGENT_PREFLIGHT_EVENT,
        run_id=resolved_run_id,
        stage=PreflightStage.STARTED.value,
        registry_digest=digest,
        enabled_agent_count=len(get_enabled_agents()),
    )
    results: list[PreflightResult] = []
    for agent in targets:
        check = AGENT_REGISTRY[agent].credential_check
        handler = _CHECK_HANDLERS[check.kind]
        available = handler(check)
        outcome = PreflightOutcome.AVAILABLE if available else PreflightOutcome.UNAVAILABLE
        reason = PreflightReason.CREDENTIAL_FOUND if available else PreflightReason.CREDENTIAL_NOT_FOUND
        logger.info(
            AGENT_PREFLIGHT_EVENT,
            run_id=resolved_run_id,
            stage=PreflightStage.COMPLETED.value,
            agent=agent.value,
            outcome=outcome.value,
            reason=reason.value,
        )
        results.append(PreflightResult(agent=agent, outcome=outcome, login_hint=check.login_hint))
    return tuple(results)


def main(argv: list[str] | None = None) -> int:
    """Run preflight for every canonical agent and print a human-readable report."""
    del argv
    print()
    print("=== Credential Check ===")
    errors = 0
    for result in run_preflight():
        label = _DISPLAY_LABEL[result.agent]
        if result.outcome is PreflightOutcome.AVAILABLE:
            print(f"  {label}: OK")
        else:
            print(f"  {label}: MISSING — {result.login_hint}")
            errors += 1
    print()
    if errors:
        print(f"WARNING: {errors} credential(s) not accessible.")
        print("         Log in from a GUI terminal, then re-run this script to verify.")
        return 1
    print("All credentials verified. Runner is ready for release automation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
