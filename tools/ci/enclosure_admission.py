"""Source-byte and closed-action admission for the separate privileged enclosure helper."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.acceptance_interpreter_metadata import IMAGE_REFERENCE, _file_identity
from tools.ci.enclosure_contract import (
    QUALIFICATION_DIGEST,
    RECIPE_DIGEST,
    STATIC_DIGEST,
    Action,
    AdmittedDeadline,
    Field,
    JsonObject,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    require_hex,
    text,
)
from tools.ci.enclosure_data import GIT, GIT_DIRECTORY, GIT_OPTIONS
from tools.ci.enclosure_guest import Purpose
from tools.ci.enclosure_journal import ActionResult, Binding
from tools.ci.enclosure_journal import Key as BindingKey
from tools.ci.enclosure_native import NativeQuery, query_native
from tools.ci.enclosure_owner import HelperOwner
from tools.ci.enclosure_owner import Key as OwnerKey

ROOT: Final = Path("/")
ENTRY: Final = Path("tools/ci/runtime_acceptance.py")
ACTUAL_SOURCE_ROOT: Final = Path(__file__).resolve().parents[2]
UTF8: Final = "utf-8"
IMAGE_SHA256: Final = "sha256"
IMAGE_SIZE_BYTES: Final = "size_bytes"
IMAGE_DEVICE: Final = "device"
IMAGE_INODE: Final = "inode"
REV_PARSE: Final = ("rev-parse", "--verify")
HEAD: Final = "HEAD"
HEAD_TREE: Final = "HEAD^{tree}"
REALIZATION_SCHEMA: Final = 1
QUALIFICATION_SETUP_VECTOR: Final = "Q2"
QUALIFICATION_SETUP_ACTIONS: Final = frozenset(
    {Action.PROVISION, Action.CREATE_PARENT, Action.START_GUEST, Action.MASK_GUEST, Action.GUEST_SETUP}
)
ERROR_SOURCE: Final = "privileged helper source, interpreter, library or realization bytes disagree with the bound run"
ERROR_DEADLINE: Final = "privileged source admission exhausted the original command/vector/outer allowance"
ERROR_PATH: Final = "privileged admission requires protected, explicitly declared source and runtime files: {path}"
REQUIRED_SOURCES: Final = frozenset(
    {
        "tools/ci/runtime_acceptance.py",
        "tools/ci/acceptance_work.py",
        "tools/ci/enclosure_inner.py",
        "tools/ci/enclosure_report.py",
        "tools/ci/enclosure_admission.py",
        "tools/ci/enclosure_contract.py",
        "tools/ci/enclosure_owner.py",
        "tools/ci/enclosure_journal.py",
        "tools/ci/enclosure_native.py",
        "tools/ci/enclosure_privileged.py",
        "tools/ci/enclosure_actions.py",
        "tools/ci/enclosure_exchange.py",
        "tools/ci/enclosure_guest_manifest.py",
        "tools/ci/enclosure_guest_evidence.py",
        "tools/ci/enclosure_payload_completion.py",
        "tools/ci/acceptance_interpreter_metadata.py",
    }
)


class Key(StrEnum):
    """Typed realization fields consumed here; review judgments remain outside this parser."""

    SOURCE_FILES = "source_files"
    OUTSIDE_RUNTIME = "outside_runtime"
    INTERPRETER = "interpreter"
    LIBRARIES = "libraries"
    PYTHON_BINARY = "python_binary"


@dataclass(frozen=True)
class SourceAdmission:
    """The exact externally selected realization bytes, not a machine-issued review approval."""

    realization_bytes: bytes
    source_root: Path
    package: StaticPackage
    binding: Binding

    def verify(self, query: NativeQuery, deadline: AdmittedDeadline) -> None:
        """Check the actual fixed source/runtime bytes and native checkout within the original action cutoff."""
        _require_time(deadline)
        record = parse_object(self.realization_bytes)
        if (
            positive_integer(record, Field.SCHEMA_VERSION) != REALIZATION_SCHEMA
            or hashlib.sha256(self.realization_bytes).hexdigest() != self.binding.realization_digest
            or record.get(BindingKey.CANDIDATE_COMMIT) != self.binding.candidate_commit
            or record.get(BindingKey.CANDIDATE_TREE) != self.binding.candidate_tree
            or record.get(BindingKey.STATIC_LOCK_DIGEST) != STATIC_DIGEST
            or record.get(BindingKey.RECIPE_DIGEST) != RECIPE_DIGEST
            or record.get(BindingKey.QUALIFICATION_DIGEST) != QUALIFICATION_DIGEST
            or hashlib.sha256(self.package.lock_bytes).hexdigest() != STATIC_DIGEST
            or hashlib.sha256(self.package.recipe_bytes).hexdigest() != RECIPE_DIGEST
            or hashlib.sha256(self.package.qualification_bytes).hexdigest() != QUALIFICATION_DIGEST
        ):
            raise ValueError(ERROR_SOURCE)
        root = self.source_root.resolve(strict=True)
        if root != ACTUAL_SOURCE_ROOT or Path(sys.argv[0]).resolve(strict=True) != root / ENTRY:
            raise ValueError(ERROR_SOURCE)
        sources = object_value(record[Key.SOURCE_FILES])
        if not REQUIRED_SOURCES <= set(sources):
            raise ValueError(ERROR_SOURCE)
        for relative, value in sources.items():
            path = Path(relative)
            if path.is_absolute() or os.pardir in path.parts:
                raise ValueError(ERROR_PATH.format(path=path))
            physical = (root / path).resolve(strict=True)
            if not physical.is_relative_to(root):
                raise ValueError(ERROR_PATH.format(path=path))
            _verify_file(root / path, object_value(value), deadline)
        self.package.validate_source(root)
        runtime = object_value(record[Key.OUTSIDE_RUNTIME])
        interpreter = object_value(runtime[Key.INTERPRETER])
        images = parse_object(self.package.lock_bytes)[Key.PYTHON_BINARY]
        libraries = runtime[Key.LIBRARIES]
        if not isinstance(images, list) or len(images) != 1 or not isinstance(libraries, list) or not libraries:
            raise ValueError(ERROR_SOURCE)
        fixed_image = object_value(images[0])
        expected_path = ROOT / text(fixed_image, Field.PATH)
        if (
            text(interpreter, Field.PATH) != str(expected_path)
            or text(interpreter, Field.SHA256) != text(fixed_image, Field.SHA256)
            or positive_integer(interpreter, Field.BYTES) != positive_integer(fixed_image, Field.BYTES)
            or IMAGE_REFERENCE.resolve(strict=True) != expected_path.resolve(strict=True)
        ):
            raise ValueError(ERROR_SOURCE)
        _verify_file(expected_path, interpreter, deadline)
        actual_image = _file_identity(IMAGE_REFERENCE)
        if actual_image[IMAGE_SHA256] != text(interpreter, Field.SHA256) or actual_image[
            IMAGE_SIZE_BYTES
        ] != positive_integer(interpreter, Field.BYTES):
            raise ValueError(ERROR_SOURCE)
        seen: set[Path] = set()
        for value in libraries:
            row = object_value(value)
            path = Path(text(row, Field.PATH))
            if not path.is_absolute() or os.pardir in path.parts or path in seen:
                raise ValueError(ERROR_PATH.format(path=path))
            seen.add(path)
            _verify_file(path, row, deadline)
        cap = positive_integer(
            object_value(parse_object(self.package.recipe_bytes)[Field.BUDGET_SECONDS]), Field.NORMAL_COMMAND_MAX
        )
        prefix = (GIT, *GIT_OPTIONS, GIT_DIRECTORY, str(root), *REV_PARSE)
        commit = query_native((*prefix, HEAD), query, deadline, cap).decode(UTF8).strip()
        tree = query_native((*prefix, HEAD_TREE), query, deadline, cap).decode(UTF8).strip()
        if commit != self.binding.candidate_commit or tree != self.binding.candidate_tree:
            raise ValueError(ERROR_SOURCE)
        _require_time(deadline)


@dataclass(frozen=True)
class ActionAdmission:
    """One fixed action, checked inside the existing journal's native serialization boundary."""

    owner: HelperOwner
    source: SourceAdmission
    action: Action
    query: NativeQuery
    maximum_seconds: int
    vector_end_ns: int | None
    command_end_ns: int | None
    qualification_vector: str | None

    def perform(self, operation: Callable[[int], ActionResult]) -> ActionResult:
        """Preserve the existing at-most-once phase graph and original absolute bounds."""
        if self.source.binding != self.owner.journal.binding or self.action not in self.owner.journal.transitions:
            raise ValueError(ERROR_SOURCE)
        purpose = Purpose(text(parse_object(self.owner.manifest_bytes), OwnerKey.PURPOSE))
        if purpose is Purpose.QUALIFICATION and (
            self.qualification_vector != QUALIFICATION_SETUP_VECTOR
            or self.vector_end_ns is None
            or self.action not in QUALIFICATION_SETUP_ACTIONS
        ):
            # Q4 uses the separately approved guest cleanup endpoint; it never fabricates payload-started here.
            raise ValueError(ERROR_SOURCE)
        return self.owner.journal.perform(
            self.action,
            operation,
            maximum_seconds=self.maximum_seconds,
            vector_end_ns=self.vector_end_ns,
            command_end_ns=self.command_end_ns,
            admission=self._admit,
        )

    def _admit(self, original_command_end: int) -> None:
        self.owner.require_original_parent()
        deadline = AdmittedDeadline(self.owner.journal.deadline.end_ns, self.vector_end_ns, original_command_end)
        self.source.verify(self.query, deadline)
        if self.owner.journal.transitions != self.source.package.transitions():
            raise ValueError(ERROR_SOURCE)
        self.owner.require_original_parent()
        _require_time(deadline)


def _require_time(deadline: AdmittedDeadline) -> None:
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_DEADLINE)


def _verify_file(path: Path, row: JsonObject, deadline: AdmittedDeadline) -> None:
    _require_time(deadline)
    require_hex(text(row, Field.SHA256), 64)
    physical = path.resolve(strict=True)
    for ancestor in (path, *path.parents, physical, *physical.parents):
        native = ancestor.lstat()
        if native.st_uid != 0 or (not stat.S_ISLNK(native.st_mode) and native.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ValueError(ERROR_PATH.format(path=path))
    before = physical.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(ERROR_PATH.format(path=path))
    identity = _file_identity(physical)
    after = physical.stat()
    if (
        identity[IMAGE_SHA256] != text(row, Field.SHA256)
        or identity[IMAGE_SIZE_BYTES] != positive_integer(row, Field.BYTES)
        or identity[IMAGE_DEVICE] != before.st_dev
        or identity[IMAGE_INODE] != before.st_ino
        or (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_mtime_ns, after.st_ctime_ns)
    ):
        raise ValueError(ERROR_SOURCE)
    _require_time(deadline)
