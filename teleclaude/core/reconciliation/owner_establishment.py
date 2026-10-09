"""Decide whether installation needs to establish the machine's first owner."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from instrukt_ai_logging import get_logger
from pydantic import ValidationError
from ruamel.yaml.error import YAMLError

from teleclaude.caller_identity import entries_for_email
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.migrations._chain import upcast
from teleclaude.config.resource_catalog import load_mapping, raw_people
from teleclaude.config.resource_contract import InvalidCandidate, PartialCommitFailure
from teleclaude.config.resources import register_first_person
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.logging_config import setup_logging
from teleclaude.paths import GLOBAL_CONFIG_PATH

logger = get_logger("teleclaude.core.reconciliation.owner_establishment")

_OWNER_NAME_ENVIRONMENT_VARIABLE = "TELECLAUDE_OWNER_NAME"
_OWNER_EMAIL_ENVIRONMENT_VARIABLE = "TELECLAUDE_OWNER_EMAIL"
_EMPTY_VALUE = ""
_LIST_SEPARATOR = ", "
_UTF8 = "utf-8"
_COMMAND_ARGUMENT = "command"
_INVALID_REGISTRY_ENTRY = "The people registry contains an invalid entry."
_REGISTRY_READ_FAILURE = "Could not read and validate the machine's people registry; installation stopped."
_OWNER_ESTABLISHMENT_FINISHED_EVENT = "install_owner_establishment_finished"
_OWNER_ESTABLISHMENT_FAILED_EVENT = "install_owner_establishment_failed"
_OWNER_NAME_PROMPT = "First administrator name: "
_OWNER_EMAIL_PROMPT = "First administrator email: "
_OWNER_ESTABLISHED = "First platform administrator registered."
_OWNER_SEED_ACCEPTED = "Owner seed accepted; first administrator registration will follow configuration validation."
_OWNER_ALREADY_PRESENT = "Owner seed matches an existing platform administrator: {email}."
_OWNER_ALREADY_OWNED = "A person is already registered; no owner seed is needed."
_OWNER_ASK_PENDING = "A first administrator will be requested after configuration validation."
_OWNER_MISSING_SEED = (
    "No person is registered. Set both TELECLAUDE_OWNER_NAME and TELECLAUDE_OWNER_EMAIL for an unattended install."
)
_OWNER_INCOMPLETE_SEED = "Owner seed is incomplete; set both TELECLAUDE_OWNER_NAME and TELECLAUDE_OWNER_EMAIL."
_OWNER_CONFLICT_ABSENT = "Owner seed conflict: {email} is absent from the people registry."
_OWNER_CONFLICT_ROLE = "Owner seed conflict: {email} is registered with platform role {role}, not admin."
_OWNER_CONFLICT_DUPLICATE = (
    "Owner seed conflict: {email} appears {count} times in the people registry with roles {roles}."
)
_OWNER_ROLE_UNDECLARED = "no role"
_OWNER_REGISTRATION_REFUSED = "First administrator registration was refused: {error}"
_OWNER_REGISTRATION_PARTIAL = "First administrator registration partially committed: {error}"
_OWNER_REGISTRATION_FAILED = "First administrator registration failed: {error}"
_OWNER_STATE_LOAD_FAILED = "registry_read_failed"
_OWNER_REGISTRATION_REFUSED_CODE = "registration_refused"
_OWNER_REGISTRATION_PARTIAL_CODE = "partially_committed"
_OWNER_REGISTRATION_FAILED_CODE = "registration_failed"


class OwnerDecision(StrEnum):
    """Terminal decision for installation's first-owner boundary."""

    ESTABLISH = "establish"
    ALREADY_OWNED = "already_owned"
    NOT_NEEDED = "not_needed"
    ASK = "ask"
    REFUSED_MISSING_SEED = "refused_missing_seed"
    REFUSED_CONFLICT = "refused_conflict"
    REFUSED_INCOMPLETE_SEED = "refused_incomplete_seed"


class OwnerEstablishmentCommand(StrEnum):
    """Operations exposed by this installation entry point."""

    DECIDE = "decide"
    ESTABLISH = "establish"


@dataclass(frozen=True)
class OwnerSeed:
    """One installation-supplied identity for the first platform administrator."""

    name: str | None
    email: str | None

    @property
    def complete(self) -> bool:
        """Whether both identity fields carry non-empty values."""
        return bool(self.name and self.name.strip() and self.email and self.email.strip())


def decide_owner(
    seed: OwnerSeed | None,
    people: Sequence[PersonEntry],
    has_terminal: bool,
) -> OwnerDecision:
    """Choose the owner action from an input seed, roster snapshot, and terminal fact."""
    if seed is not None and not seed.complete:
        return OwnerDecision.REFUSED_INCOMPLETE_SEED
    if not people:
        if seed is not None:
            return OwnerDecision.ESTABLISH
        if has_terminal:
            return OwnerDecision.ASK
        return OwnerDecision.REFUSED_MISSING_SEED
    if seed is None:
        return OwnerDecision.NOT_NEEDED
    matches = entries_for_email(people, seed.email or _EMPTY_VALUE)
    if len(matches) == 1 and matches[0].role == HUMAN_ROLE_ADMIN:
        return OwnerDecision.ALREADY_OWNED
    return OwnerDecision.REFUSED_CONFLICT


def _read_owner_seed() -> OwnerSeed | None:
    """Read the installation-only owner seed without persisting its values."""
    name = os.environ.get(_OWNER_NAME_ENVIRONMENT_VARIABLE)  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal (installer-supplied owner seed)
    email = os.environ.get(_OWNER_EMAIL_ENVIRONMENT_VARIABLE)  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal (installer-supplied owner seed)
    if name is None and email is None:
        return None
    return OwnerSeed(name=name, email=email)


def _read_people_roster() -> list[PersonEntry]:
    """Read and validate one atomic people registry snapshot without writing state."""
    if not GLOBAL_CONFIG_PATH.exists():
        return []
    stored_text = GLOBAL_CONFIG_PATH.read_text(encoding=_UTF8)
    stored = load_mapping(stored_text, GLOBAL_CONFIG_PATH)
    global_ref = SubjectRef(ConfigSubjectKind.GLOBAL)
    global_raw = dict(upcast(stored, global_ref))
    entries = raw_people(global_raw)
    people: list[PersonEntry] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError(_INVALID_REGISTRY_ENTRY)
        try:
            people.append(PersonEntry.model_validate(entry))
        except ValidationError as exc:
            raise ValueError(_INVALID_REGISTRY_ENTRY) from exc
    return people


def _decision_message(decision: OwnerDecision, seed: OwnerSeed | None, people: Sequence[PersonEntry]) -> str:
    if decision is OwnerDecision.ESTABLISH:
        return _OWNER_SEED_ACCEPTED
    if decision is OwnerDecision.ALREADY_OWNED:
        assert seed is not None and seed.email is not None
        return _OWNER_ALREADY_PRESENT.format(email=seed.email.strip())
    if decision is OwnerDecision.NOT_NEEDED:
        return _OWNER_ALREADY_OWNED
    if decision is OwnerDecision.ASK:
        return _OWNER_ASK_PENDING
    if decision is OwnerDecision.REFUSED_MISSING_SEED:
        return _OWNER_MISSING_SEED
    if decision is OwnerDecision.REFUSED_INCOMPLETE_SEED:
        return _OWNER_INCOMPLETE_SEED
    assert seed is not None and seed.email is not None
    matches = entries_for_email(people, seed.email)
    if not matches:
        return _OWNER_CONFLICT_ABSENT.format(email=seed.email.strip())
    roles = [_role_label(entry) for entry in matches]
    if len(matches) == 1:
        return _OWNER_CONFLICT_ROLE.format(email=seed.email.strip(), role=roles[0])
    return _OWNER_CONFLICT_DUPLICATE.format(
        email=seed.email.strip(),
        count=len(matches),
        roles=_LIST_SEPARATOR.join(roles),
    )


def _role_label(person: PersonEntry) -> str:
    return person.role if person.role is not None else _OWNER_ROLE_UNDECLARED


def _record_outcome(
    command: OwnerEstablishmentCommand,
    outcome: str,
    people_count: int,
    has_terminal: bool,
    exit_code: int,
    failure_code: str | None = None,
) -> None:
    logger.info(
        _OWNER_ESTABLISHMENT_FINISHED_EVENT,
        command=command.value,
        outcome=outcome,
        people_count=people_count,
        has_terminal=has_terminal,
        exit_code=exit_code,
        failure_code=failure_code,
    )


def _report_decision(
    command: OwnerEstablishmentCommand,
    decision: OwnerDecision,
    seed: OwnerSeed | None,
    people: Sequence[PersonEntry],
    has_terminal: bool,
) -> int:
    refused = decision in {
        OwnerDecision.REFUSED_MISSING_SEED,
        OwnerDecision.REFUSED_CONFLICT,
        OwnerDecision.REFUSED_INCOMPLETE_SEED,
    }
    message = _decision_message(decision, seed, people)
    exit_code = 1 if refused else 0
    if refused:
        print(message, file=sys.stderr)
    else:
        print(message)
    _record_outcome(
        command,
        decision.value,
        len(people),
        has_terminal,
        exit_code,
        decision.value if refused else None,
    )
    return exit_code


def _read_state_or_fail(
    command: OwnerEstablishmentCommand,
    has_terminal: bool,
) -> tuple[list[PersonEntry] | None, int | None]:
    try:
        return _read_people_roster(), None
    except (OSError, ValueError, YAMLError) as exc:
        print(_REGISTRY_READ_FAILURE, file=sys.stderr)
        logger.error(
            _OWNER_ESTABLISHMENT_FAILED_EVENT,
            command=command.value,
            outcome=_OWNER_STATE_LOAD_FAILED,
            has_terminal=has_terminal,
            error_type=type(exc).__name__,
        )
        return None, 1


def _prompt_for_seed() -> OwnerSeed:
    """Ask a terminal operator for the first administrator's identity."""
    try:
        name = input(_OWNER_NAME_PROMPT).strip()
        email = input(_OWNER_EMAIL_PROMPT).strip()
    except EOFError:
        return OwnerSeed(name=None, email=None)
    return OwnerSeed(name=name or None, email=email or None)


def _register_owner(seed: OwnerSeed, people_count: int, has_terminal: bool) -> int:
    assert seed.name is not None and seed.email is not None
    try:
        register_first_person(seed.name.strip(), seed.email.strip())
    except PartialCommitFailure as exc:
        print(_OWNER_REGISTRATION_PARTIAL.format(error=exc), file=sys.stderr)
        _record_outcome(
            OwnerEstablishmentCommand.ESTABLISH,
            OwnerDecision.ESTABLISH.value,
            people_count,
            has_terminal,
            1,
            _OWNER_REGISTRATION_PARTIAL_CODE,
        )
        return 1
    except InvalidCandidate as exc:
        print(_OWNER_REGISTRATION_REFUSED.format(error=exc), file=sys.stderr)
        _record_outcome(
            OwnerEstablishmentCommand.ESTABLISH,
            OwnerDecision.REFUSED_CONFLICT.value,
            people_count,
            has_terminal,
            1,
            _OWNER_REGISTRATION_REFUSED_CODE,
        )
        return 1
    except (OSError, ValueError, ValidationError) as exc:
        print(_OWNER_REGISTRATION_FAILED.format(error=exc), file=sys.stderr)
        _record_outcome(
            OwnerEstablishmentCommand.ESTABLISH,
            OwnerDecision.ESTABLISH.value,
            people_count,
            has_terminal,
            1,
            _OWNER_REGISTRATION_FAILED_CODE,
        )
        return 1
    print(_OWNER_ESTABLISHED)
    _record_outcome(
        OwnerEstablishmentCommand.ESTABLISH,
        OwnerDecision.ESTABLISH.value,
        people_count + 1,
        has_terminal,
        0,
    )
    return 0


def _run_decide(seed: OwnerSeed | None, people: Sequence[PersonEntry], has_terminal: bool) -> int:
    decision = decide_owner(seed, people, has_terminal)
    return _report_decision(OwnerEstablishmentCommand.DECIDE, decision, seed, people, has_terminal)


def _run_establish(seed: OwnerSeed | None, people: list[PersonEntry], has_terminal: bool) -> int:
    decision = decide_owner(seed, people, has_terminal)
    if decision is OwnerDecision.ASK:
        seed = _prompt_for_seed()
        refreshed_people, failure_code = _read_state_or_fail(OwnerEstablishmentCommand.ESTABLISH, has_terminal)
        if refreshed_people is None:
            return failure_code or 1
        people = refreshed_people
        decision = decide_owner(seed, people, has_terminal)
    if decision is OwnerDecision.ESTABLISH:
        assert seed is not None
        return _register_owner(seed, len(people), has_terminal)
    return _report_decision(OwnerEstablishmentCommand.ESTABLISH, decision, seed, people, has_terminal)


def _parse_command() -> OwnerEstablishmentCommand:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_COMMAND_ARGUMENT, choices=[command.value for command in OwnerEstablishmentCommand])
    return OwnerEstablishmentCommand(parser.parse_args().command)


def main() -> int:
    """Run one owner-decision or owner-establishment installation step."""
    setup_logging()
    command = _parse_command()
    has_terminal = sys.stdin.isatty()
    seed = _read_owner_seed()
    people, failure_code = _read_state_or_fail(command, has_terminal)
    if people is None:
        return failure_code or 1
    if command is OwnerEstablishmentCommand.DECIDE:
        return _run_decide(seed, people, has_terminal)
    return _run_establish(seed, people, has_terminal)


if __name__ == "__main__":
    raise SystemExit(main())
