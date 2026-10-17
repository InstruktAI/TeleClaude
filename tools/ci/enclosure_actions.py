"""Fixed native manager effects, distinct from original-supervisor phase observations."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import (
    Action,
    AdmittedDeadline,
    Field,
    JsonObject,
    JsonValue,
    Parameter,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_guest import close_evidence_descriptors
from tools.ci.enclosure_journal import ActionResult
from tools.ci.enclosure_owner import Key as OwnerKey
from tools.ci.enclosure_privileged import PrivilegedAction

BUSCTL: Final = "/usr/bin/busctl"
BUS_OPTIONS: Final = (
    "--system",
    "--json=short",
    "--no-pager",
    "--auto-start=no",
    "--allow-interactive-authorization=no",
)
CALL: Final = "call"
SYSTEMD: Final = "org.freedesktop.systemd1"
MANAGER_PATH: Final = "/org/freedesktop/systemd1"
MANAGER: Final = "org.freedesktop.systemd1.Manager"
MACHINE: Final = "--machine={machine}"
TIMEOUT: Final = "--timeout={seconds}s"
JOB_PREFIX: Final = "/org/freedesktop/systemd1/job/"
JOB_FAIL: Final = "fail"
JOB_START: Final = "start"
UNIT_PREFIX: Final = "/org/freedesktop/systemd1/unit/"
ARRAY_ONE: Final = "1"
TRUE: Final = "true"
FALSE: Final = "false"
NULL_TARGET: Final = "/dev/null"
SYMLINK_CHANGE: Final = "symlink"
GUEST_SETUP: Final = "tc-ra-guest-setup.service"
GUEST_PAYLOAD: Final = "tc-ra-payload.service"
GUEST_POWEROFF: Final = "tc-ra-poweroff.service"
NANOSECONDS: Final = 1_000_000_000
ERROR_NATIVE: Final = "native manager mutation did not return a complete on-time receipt"
ERROR_RUNTIME: Final = "the declared runtime unit/configuration path is occupied or not protected: {path}"
ERROR_ACTION: Final = "the fixed native producer is not yet implemented: {action}"
ERROR_PHASE: Final = "native mutation receipt does not establish the requested supervisor phase"


class Key(StrEnum):
    """Structured native receipts, with no P4 or phase-success predicate."""

    TYPE = "type"
    DATA = "data"
    UNIT_DESTINATIONS = "unit_destinations"
    AUTHORITY = "authority"
    UNIT_NAME = "unit_name"
    JOB_IDENTIFIER = "job_identifier"
    JOB_PATH = "job_path"
    UNIT_PATH = "unit_path"
    JOB_TYPE = "job_type"
    ACCEPTED_JOBS = "accepted_jobs"
    RAW_REPLY = "raw_reply"
    RUNTIME_FILES = "runtime_files"
    MASK_CHANGES = "mask_changes"
    PARENT_CREATED = "parent_created"


class Member(StrEnum):
    """Only the exact native mutation methods required by these producers."""

    RELOAD = "Reload"
    START = "StartUnit"
    ENQUEUE = "EnqueueUnitJob"
    MASK = "MaskUnitFiles"


class Signature(StrEnum):
    """Native request/reply types, verified before any receipt is consumed."""

    EMPTY = ""
    STRINGS = "ss"
    THREE_STRINGS = "sss"
    TRANSACTION = "uososa(uosos)"
    MASK_INPUT = "asbb"
    OBJECT = "o"
    CHANGES = "a(sss)"


class Authority(StrEnum):
    """Keep host and guest jobs in distinct native manager namespaces."""

    HOST = "host"
    GUEST = "guest"


class Template(StrEnum):
    """The three owned host files of the reviewed concrete recipe."""

    PARENT = "parent.slice"
    INSTANCE = "instance.conf"
    SETTINGS = "nspawn.settings"


@dataclass(frozen=True)
class NativeMutation:
    """An actual native acknowledgment, never original-object binding, settlement or seal proof."""

    action: Action
    evidence: Mapping[str, JsonValue]


def _deadline(context: PrivilegedAction, end_ns: int) -> AdmittedDeadline:
    original = context.commands.deadline
    return AdmittedDeadline(original.outer_end_ns, original.vector_end_ns, min(end_ns, original.effective_end()))


def _call(
    context: PrivilegedAction,
    end_ns: int,
    member: Member,
    signature: Signature,
    arguments: tuple[str, ...],
    reply_signature: Signature,
    *,
    guest: bool = False,
) -> JsonObject:
    recipe = parse_object(context.owner.package.recipe_bytes)
    cap = positive_integer(object_value(recipe[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX)
    end = _deadline(context, end_ns).command_end(cap)
    remaining = (end - time.monotonic_ns()) / NANOSECONDS
    if remaining <= 0:
        raise TimeoutError(ERROR_NATIVE)
    options: tuple[str, ...] = BUS_OPTIONS
    if guest:
        record = parse_object(context.owner.manifest_bytes)
        machine = Path(text(record, OwnerKey.ROOTFS)).name
        options = (*options, MACHINE.format(machine=machine))
    reply = context.commands.query(
        (
            BUSCTL,
            *options,
            TIMEOUT.format(seconds=remaining),
            CALL,
            SYSTEMD,
            MANAGER_PATH,
            MANAGER,
            member.value,
            signature.value,
            *arguments,
        ),
        end,
    )
    if reply.status != 0 or not reply.complete or time.monotonic_ns() >= end:
        raise ValueError(ERROR_NATIVE)
    if reply_signature is Signature.EMPTY:
        if reply.stdout.strip():
            raise ValueError(ERROR_NATIVE)
        return {}
    result = parse_object(reply.stdout)
    if result.get(Key.TYPE) != reply_signature or not isinstance(result.get(Key.DATA), list):
        raise ValueError(ERROR_NATIVE)
    return result


def _start(context: PrivilegedAction, end_ns: int, unit: str, authority: Authority) -> JsonObject:
    if authority is Authority.HOST:
        return _enqueue_host_start(context, end_ns, unit)
    reply = _call(
        context,
        end_ns,
        Member.START,
        Signature.STRINGS,
        (unit, JOB_FAIL),
        Signature.OBJECT,
        guest=authority is Authority.GUEST,
    )
    body = reply.get(Key.DATA)
    if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], str):
        raise ValueError(ERROR_NATIVE)
    path = body[0]
    if not path.startswith(JOB_PREFIX):
        raise ValueError(ERROR_NATIVE)
    suffix = path[len(JOB_PREFIX) :]
    if not suffix.isascii() or not suffix.isdecimal() or not 0 < int(suffix) <= 0xFFFFFFFF:
        raise ValueError(ERROR_NATIVE)
    return {
        Key.AUTHORITY: authority.value,
        Key.UNIT_NAME: unit,
        Key.JOB_IDENTIFIER: int(suffix),
        Key.JOB_PATH: path,
        Key.RAW_REPLY: reply,
    }


def _transaction_job(value: list[JsonValue]) -> JsonObject:
    if len(value) != 5:
        raise ValueError(ERROR_NATIVE)
    identifier, path, name, unit_path, job_type = value
    if (
        type(identifier) is not int
        or not 0 < identifier <= 0xFFFFFFFF
        or path != JOB_PREFIX + str(identifier)
        or not isinstance(name, str)
        or not name
        or Path(name).name != name
        or not isinstance(unit_path, str)
        or not unit_path.startswith(UNIT_PREFIX)
        or unit_path == UNIT_PREFIX
        or not isinstance(job_type, str)
        or not job_type
    ):
        raise ValueError(ERROR_NATIVE)
    return {
        Key.JOB_IDENTIFIER: identifier,
        Key.JOB_PATH: path,
        Key.UNIT_NAME: name,
        Key.UNIT_PATH: unit_path,
        Key.JOB_TYPE: job_type,
    }


def _enqueue_host_start(context: PrivilegedAction, end_ns: int, unit: str) -> JsonObject:
    reply = _call(
        context,
        end_ns,
        Member.ENQUEUE,
        Signature.THREE_STRINGS,
        (unit, JOB_START, JOB_FAIL),
        Signature.TRANSACTION,
    )
    body = reply.get(Key.DATA)
    if not isinstance(body, list) or len(body) != 6 or not isinstance(body[5], list):
        raise ValueError(ERROR_NATIVE)
    anchor = _transaction_job(body[:5])
    if anchor[Key.UNIT_NAME] != unit or anchor[Key.JOB_TYPE] != JOB_START:
        raise ValueError(ERROR_NATIVE)
    jobs: list[JsonValue] = [anchor]
    identifiers = {positive_integer(anchor, Key.JOB_IDENTIFIER)}
    for value in body[5]:
        if not isinstance(value, list):
            raise ValueError(ERROR_NATIVE)
        job = _transaction_job(value)
        identifier = positive_integer(job, Key.JOB_IDENTIFIER)
        if identifier in identifiers:
            raise ValueError(ERROR_NATIVE)
        identifiers.add(identifier)
        jobs.append(job)
    return {
        **anchor,
        Key.AUTHORITY: Authority.HOST.value,
        Key.ACCEPTED_JOBS: jobs,
        Key.RAW_REPLY: reply,
    }


def _reload(context: PrivilegedAction, end_ns: int) -> None:
    _call(context, end_ns, Member.RELOAD, Signature.EMPTY, (), Signature.EMPTY)


def _runtime_file(context: PrivilegedAction, template: Template, end_ns: int, *, new_parent: bool) -> JsonObject:
    deadline = _deadline(context, end_ns)
    _require_time(deadline)
    binding = context.owner.journal.binding
    package = context.owner.package
    recipe = parse_object(package.recipe_bytes)
    destinations = object_value(recipe[Key.UNIT_DESTINATIONS])
    parameters: dict[str, str] = {Parameter.RUN_TOKEN: binding.run_token}
    target = Path(text(destinations, template).format_map(parameters))
    data = package.render(
        run_token=binding.run_token,
        candidate_sha=binding.candidate_commit,
        candidate_tree=binding.candidate_tree,
        selection=Signature.EMPTY.value,
    )[template]
    base_fd = _runtime_directory(target.parent.parent)
    parent_fd = -1
    descriptor = -1
    try:
        _require_time(deadline)
        created = False
        try:
            os.mkdir(target.parent.name, mode=0o755, dir_fd=base_fd)
            created = True
            os.fsync(base_fd)
        except FileExistsError:
            if new_parent:
                raise ValueError(ERROR_RUNTIME.format(path=target)) from None
        parent_fd = _runtime_directory(target.parent)
        if created:
            os.fchmod(parent_fd, 0o755)
        _require_time(deadline)
        descriptor = os.open(
            target.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644, dir_fd=parent_fd
        )
        os.fchmod(descriptor, 0o644)
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError(ERROR_RUNTIME.format(path=target))
            offset += written
        os.fsync(descriptor)
        os.fsync(parent_fd)
        if os.pread(descriptor, len(data) + 1, 0) != data:
            raise ValueError(ERROR_RUNTIME.format(path=target))
        _require_time(deadline)
        return {
            Field.PATH: str(target),
            Field.SHA256: hashlib.sha256(data).hexdigest(),
            Field.BYTES: len(data),
            Key.PARENT_CREATED: created,
        }
    finally:
        close_evidence_descriptors(descriptor, parent_fd, base_fd)


def _require_time(deadline: AdmittedDeadline) -> None:
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_NATIVE)


def _runtime_directory(path: Path) -> int:
    for ancestor in (path, *path.parents):
        native = ancestor.lstat()
        if native.st_uid != 0 or not stat.S_ISDIR(native.st_mode) or native.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError(ERROR_RUNTIME.format(path=path))
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def _create_parent(context: PrivilegedAction, end_ns: int) -> NativeMutation:
    file = _runtime_file(context, Template.PARENT, end_ns, new_parent=False)
    _reload(context, end_ns)
    unit = text(parse_object(context.owner.manifest_bytes), OwnerKey.PARENT_UNIT)
    evidence = _start(context, end_ns, unit, Authority.HOST)
    evidence[Key.RUNTIME_FILES] = [file]
    return NativeMutation(Action.CREATE_PARENT, evidence)


def _start_guest(context: PrivilegedAction, end_ns: int) -> NativeMutation:
    instance = _runtime_file(context, Template.INSTANCE, end_ns, new_parent=True)
    settings = _runtime_file(context, Template.SETTINGS, end_ns, new_parent=False)
    _reload(context, end_ns)
    unit = text(parse_object(context.owner.manifest_bytes), OwnerKey.GUEST_UNIT)
    evidence = _start(context, end_ns, unit, Authority.HOST)
    evidence[Key.RUNTIME_FILES] = [instance, settings]
    return NativeMutation(Action.START_GUEST, evidence)


def _mask_guest(context: PrivilegedAction, end_ns: int) -> NativeMutation:
    record = parse_object(context.owner.manifest_bytes)
    unit = text(record, OwnerKey.GUEST_UNIT)
    recipe = parse_object(context.owner.package.recipe_bytes)
    destinations = object_value(recipe[Key.UNIT_DESTINATIONS])
    parameters: dict[str, str] = {Parameter.RUN_TOKEN: context.owner.journal.binding.run_token}
    mask = Path(text(destinations, Template.PARENT).format_map(parameters)).parent / unit
    try:
        mask.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError(ERROR_RUNTIME.format(path=mask))
    reply = _call(context, end_ns, Member.MASK, Signature.MASK_INPUT, (ARRAY_ONE, unit, TRUE, FALSE), Signature.CHANGES)
    body = reply.get(Key.DATA)
    if body != [[[SYMLINK_CHANGE, str(mask), NULL_TARGET]]]:
        raise ValueError(ERROR_NATIVE)
    _reload(context, end_ns)
    native = mask.lstat()
    if not stat.S_ISLNK(native.st_mode) or native.st_uid != 0 or os.readlink(mask) != NULL_TARGET:
        raise ValueError(ERROR_RUNTIME.format(path=mask))
    return NativeMutation(Action.MASK_GUEST, {Key.UNIT_NAME: unit, Key.MASK_CHANGES: reply})


def _guest_setup(context: PrivilegedAction, end_ns: int) -> NativeMutation:
    return NativeMutation(Action.GUEST_SETUP, _start(context, end_ns, GUEST_SETUP, Authority.GUEST))


def _start_payload(context: PrivilegedAction, end_ns: int) -> NativeMutation:
    return NativeMutation(Action.START_PAYLOAD, _start(context, end_ns, GUEST_PAYLOAD, Authority.GUEST))


def _poweroff(context: PrivilegedAction, end_ns: int) -> NativeMutation:
    return NativeMutation(Action.POWEROFF, _start(context, end_ns, GUEST_POWEROFF, Authority.GUEST))


NATIVE_PRODUCERS: Final[Mapping[Action, Callable[[PrivilegedAction, int], NativeMutation]]] = {
    Action.CREATE_PARENT: _create_parent,
    Action.START_GUEST: _start_guest,
    Action.MASK_GUEST: _mask_guest,
    Action.GUEST_SETUP: _guest_setup,
    Action.START_PAYLOAD: _start_payload,
    Action.POWEROFF: _poweroff,
}


def dispatch_action(
    context: PrivilegedAction,
    observe_phase: Callable[[NativeMutation, int], ActionResult],
) -> ActionResult:
    """Admit a fixed native producer, then require the original supervisor's actual phase result."""
    action = context.admission.action
    if action not in NATIVE_PRODUCERS:
        raise ValueError(ERROR_ACTION.format(action=action))

    def operation(end_ns: int) -> ActionResult:
        mutation = NATIVE_PRODUCERS[action](context, end_ns)
        if mutation.action is not action:
            raise ValueError(ERROR_PHASE)
        return observe_phase(mutation, end_ns)

    return context.perform(operation)
