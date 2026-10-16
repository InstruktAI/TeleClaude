"""Static bindings and rendering for the acceptance harness's reviewed enclosure."""

from __future__ import annotations

import hashlib
import json
import math
import string
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

UTF8: Final = "utf-8"
STATIC_FILE: Final = "static-lock.json"
RECIPE_FILE: Final = "enclosure-recipes.json"
QUALIFICATION_FILE: Final = "qualification.json"
STATIC_DIGEST: Final = "e37697d50acf36fd7df5824561c5a68afb7719948e7177ce8055326bebd38c78"
RECIPE_DIGEST: Final = "6ea0ae4d1841f3de946b77d9e3f6a74e55965f2d30942e198547aa797fa46b7d"
QUALIFICATION_DIGEST: Final = "45ee1a7d7da7a7df7135ea2a324dcb7f33076ce81f73ca498a8e73cde102ebb1"
SELECTION_CHARACTERS: Final = frozenset(string.ascii_letters + string.digits + "-_,")
HEX_CHARACTERS: Final = frozenset(string.hexdigits.lower())
SYSTEMD_EMPTY_ARGUMENT: Final = '""'
SCHEMA_VERSION: Final = 1
NANOSECONDS: Final = 1_000_000_000
ERROR_JSON: Final = "enclosure input is not a finite JSON object"
ERROR_BINDING: Final = "enclosure static binding mismatch: {name}"
ERROR_FIELD: Final = "invalid enclosure field: {field}"
ERROR_RENDER: Final = "undeclared enclosure template parameter: {name}"
ERROR_BUDGET: Final = "the original enclosure deadline cannot admit this action and its closure reserve"


class Action(StrEnum):
    """The mutating action vocabulary of the reviewed helper protocol."""

    PROVISION = "provision"
    CREATE_PARENT = "create-parent"
    START_GUEST = "start-guest"
    MASK_GUEST = "mask-guest"
    GUEST_SETUP = "guest-setup"
    START_PAYLOAD = "start-payload"
    POWEROFF = "poweroff"
    OBSERVE = "observe"
    EXTRACT = "extract"
    RELEASE = "release"


class Phase(StrEnum):
    """The normal action progression declared by the static recipe."""

    OWNED = "owned"
    PREFLIGHT = "preflight"
    PARENT_BOUND = "parent-bound"
    GUEST_STARTED = "guest-started"
    ADMISSION_SEALED = "admission-sealed"
    GUEST_CONFIGURED = "guest-configured"
    PAYLOAD_STARTED = "payload-started"
    SHUTDOWN_REQUESTED = "shutdown-requested"
    P4_OBSERVED = "p4-observed"
    EVIDENCE_READBACK = "evidence-readback"
    RESOURCES_RELEASED = "resources-released"


class Field(StrEnum):
    """Structured keys consumed from the reviewed static files."""

    SCHEMA_VERSION = "schema_version"
    RECIPE_SHA256 = "recipe_sha256"
    QUALIFICATION_SHA256 = "qualification_sha256"
    SOURCE_LOCKS = "source_dependency_locks"
    PATH = "path"
    SHA256 = "sha256"
    BYTES = "bytes"
    UTF8 = "utf8"
    UNITS = "units"
    HELPER_PROTOCOL = "helper_protocol"
    MUTATING_ACTIONS = "mutating_actions"
    ACTION = "action"
    FROM = "from"
    TO = "to"
    MAX_ATTEMPTS = "max_attempts"
    BUDGET_SECONDS = "budget_seconds"
    RUNTIME_OUTER_MAX = "runtime_outer_max"
    CLOSURE_EXPORT_RESERVE = "closure_export_reserve"
    NORMAL_COMMAND_MAX = "normal_command_max"


class Parameter(StrEnum):
    """The substitutions admitted by the static unit templates."""

    RUN_TOKEN = "run_token"
    CANDIDATE_SHA = "candidate_sha"
    CANDIDATE_TREE = "candidate_tree"
    SELECTION = "selection"


class Cutoff(StrEnum):
    """Independent absolute cutoffs preserved at an admitted process boundary."""

    OUTER_END_NS = "outer_end_ns"
    VECTOR_END_NS = "vector_end_ns"
    COMMAND_END_NS = "command_end_ns"


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in cast(list[object], value)]
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        if all(isinstance(key, str) for key in mapping):
            return {cast(str, key): _json_value(item) for key, item in mapping.items()}
    raise ValueError(ERROR_JSON)


def object_value(value: JsonValue) -> JsonObject:
    """Validate the object boundary before accessing declared fields."""
    if not isinstance(value, dict):
        raise ValueError(ERROR_JSON)
    return value


def parse_object(data: bytes) -> JsonObject:
    """Decode finite JSON without accepting duplicate object keys."""
    parsed: object = json.loads(data, object_pairs_hook=_unique_object)
    return object_value(_json_value(parsed))


def _unique_object(pairs: list[tuple[str, object]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(ERROR_JSON)
        result[key] = _json_value(value)
    return result


def text(record: Mapping[str, JsonValue], key: str) -> str:
    """Read a required textual field without coercion."""
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(ERROR_FIELD.format(field=key))
    return value


def positive_integer(record: Mapping[str, JsonValue], key: str) -> int:
    """Read a positive integer; booleans are not integer declarations."""
    value = record.get(key)
    if type(value) is not int or value <= 0:
        raise ValueError(ERROR_FIELD.format(field=key))
    return value


def require_hex(value: str, length: int) -> None:
    """Validate an immutable identity before using it in an owned address."""
    if len(value) != length or not set(value) <= HEX_CHARACTERS:
        raise ValueError(ERROR_FIELD.format(field=value))


@dataclass(frozen=True)
class Transition:
    """One exact normal-path edge, read from the authenticated recipe bytes."""

    action: Action
    before: Phase
    after: Phase


@dataclass(frozen=True)
class StaticPackage:
    """The fixed package and source dependency basis; no host facts are implied."""

    lock_bytes: bytes
    recipe_bytes: bytes
    qualification_bytes: bytes

    @classmethod
    def load(cls, directory: Path, source_root: Path) -> StaticPackage:
        """Admit only the exact independently reviewed package and matching source locks."""
        values: list[bytes] = []
        for name, expected in (
            (STATIC_FILE, STATIC_DIGEST),
            (RECIPE_FILE, RECIPE_DIGEST),
            (QUALIFICATION_FILE, QUALIFICATION_DIGEST),
        ):
            data = (directory / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(ERROR_BINDING.format(name=name))
            record = parse_object(data)
            if type(record.get(Field.SCHEMA_VERSION)) is not int or record[Field.SCHEMA_VERSION] != SCHEMA_VERSION:
                raise ValueError(ERROR_FIELD.format(field=Field.SCHEMA_VERSION))
            values.append(data)
        package = cls(*values)
        package.validate_source(source_root)
        package.transitions()
        return package

    def validate_source(self, source_root: Path) -> None:
        """Check the existing source-owned installer/dependency basis without changing it."""
        lock = parse_object(self.lock_bytes)
        if (
            lock.get(Field.RECIPE_SHA256) != RECIPE_DIGEST
            or lock.get(Field.QUALIFICATION_SHA256) != QUALIFICATION_DIGEST
        ):
            raise ValueError(ERROR_BINDING.format(name=STATIC_FILE))
        declarations = lock.get(Field.SOURCE_LOCKS)
        if not isinstance(declarations, list) or not declarations:
            raise ValueError(ERROR_FIELD.format(field=Field.SOURCE_LOCKS))
        root = source_root.resolve(strict=True)
        for declaration in declarations:
            row = object_value(declaration)
            relative = Path(text(row, Field.PATH))
            path = (root / relative).resolve(strict=True)
            if relative.is_absolute() or not path.is_relative_to(root):
                raise ValueError(ERROR_FIELD.format(field=Field.PATH))
            data = path.read_bytes()
            if len(data) != positive_integer(row, Field.BYTES) or hashlib.sha256(data).hexdigest() != text(
                row, Field.SHA256
            ):
                raise ValueError(ERROR_BINDING.format(name=str(relative)))

    def transitions(self) -> dict[Action, Transition]:
        """Read the closed action graph, retaining the recipe's exact edge preconditions."""
        recipe = parse_object(self.recipe_bytes)
        protocol = object_value(recipe[Field.HELPER_PROTOCOL])
        rows = protocol[Field.MUTATING_ACTIONS]
        if not isinstance(rows, list):
            raise ValueError(ERROR_FIELD.format(field=Field.MUTATING_ACTIONS))
        result: dict[Action, Transition] = {}
        for value in rows:
            row = object_value(value)
            action = Action(text(row, Field.ACTION))
            if action in result or positive_integer(row, Field.MAX_ATTEMPTS) != 1:
                raise ValueError(ERROR_FIELD.format(field=action))
            result[action] = Transition(action, Phase(text(row, Field.FROM)), Phase(text(row, Field.TO)))
        if set(result) != set(Action):
            raise ValueError(ERROR_FIELD.format(field=Field.MUTATING_ACTIONS))
        return result

    def render(self, *, run_token: str, candidate_sha: str, candidate_tree: str, selection: str) -> dict[str, bytes]:
        """Render only declared substitutions, preserving a selected list as one systemd argument."""
        require_hex(run_token, 32)
        require_hex(candidate_sha, 40)
        require_hex(candidate_tree, 40)
        if not set(selection) <= SELECTION_CHARACTERS:
            raise ValueError(ERROR_FIELD.format(field=Parameter.SELECTION))
        parameters = {
            Parameter.RUN_TOKEN.value: run_token,
            Parameter.CANDIDATE_SHA.value: candidate_sha,
            Parameter.CANDIDATE_TREE.value: candidate_tree,
            Parameter.SELECTION.value: selection or SYSTEMD_EMPTY_ARGUMENT,
        }
        units = object_value(parse_object(self.recipe_bytes)[Field.UNITS])
        rendered: dict[str, bytes] = {}
        formatter = string.Formatter()
        for name, value in units.items():
            row = object_value(value)
            template = text(row, Field.UTF8)
            if hashlib.sha256(template.encode(UTF8)).hexdigest() != text(row, Field.SHA256):
                raise ValueError(ERROR_BINDING.format(name=name))
            for _, field, format_spec, conversion in formatter.parse(template):
                if field is not None and (field not in parameters or format_spec or conversion):
                    raise ValueError(ERROR_RENDER.format(name=field))
            rendered[name] = template.format_map(parameters).encode(UTF8)
        return rendered


@dataclass(frozen=True)
class AdmittedDeadline:
    """Original absolute bounds, composed without relabelling or resetting any of them."""

    outer_end_ns: int
    vector_end_ns: int | None
    command_end_ns: int | None

    @classmethod
    def from_record(cls, record: Mapping[str, JsonValue], *, require_vector: bool) -> AdmittedDeadline:
        """Require explicit nullable cutoffs; a missing handoff field is never an open allowance."""
        outer = positive_integer(record, Cutoff.OUTER_END_NS)
        optional: list[int | None] = []
        for key in (Cutoff.VECTOR_END_NS, Cutoff.COMMAND_END_NS):
            if key not in record:
                raise ValueError(ERROR_FIELD.format(field=key))
            value = record[key]
            if value is None:
                optional.append(None)
            elif type(value) is int and value > 0:
                optional.append(value)
            else:
                raise ValueError(ERROR_FIELD.format(field=key))
        if require_vector and optional[0] is None:
            raise ValueError(ERROR_FIELD.format(field=Cutoff.VECTOR_END_NS))
        return cls(outer, optional[0], optional[1])

    def effective_end(self) -> int:
        """Keep all original fields and return only their intersection."""
        return min(value for value in (self.outer_end_ns, self.vector_end_ns, self.command_end_ns) if value is not None)

    def command_end(self, maximum_seconds: float) -> int:
        """Intersect the admitted bounds with the current command's own cap."""
        if not math.isfinite(maximum_seconds) or maximum_seconds <= 0:
            raise ValueError(ERROR_BUDGET)
        now = time.monotonic_ns()
        end = min(self.effective_end(), now + int(maximum_seconds * NANOSECONDS))
        if end <= now:
            raise TimeoutError(ERROR_BUDGET)
        return end


@dataclass(frozen=True)
class Deadline:
    """One boot-local monotonic end, shared by every action of the owned run."""

    started_ns: int
    end_ns: int
    reserve_ns: int

    @classmethod
    def begin(cls, package: StaticPackage) -> Deadline:
        """Start the runtime budget once from the reviewed declaration."""
        budget = object_value(parse_object(package.recipe_bytes)[Field.BUDGET_SECONDS])
        outer = positive_integer(budget, Field.RUNTIME_OUTER_MAX)
        reserve = positive_integer(budget, Field.CLOSURE_EXPORT_RESERVE)
        if reserve >= outer:
            raise ValueError(ERROR_BUDGET)
        started = time.monotonic_ns()
        return cls(started, started + outer * NANOSECONDS, reserve * NANOSECONDS)

    def allowance(
        self, maximum_seconds: float, *, vector_end_ns: int | None = None, preserve_reserve: bool = False
    ) -> float:
        """Return the least command/vector/outer allowance without resetting any end."""
        if not math.isfinite(maximum_seconds) or maximum_seconds <= 0:
            raise ValueError(ERROR_BUDGET)
        outer_available_end = self.end_ns - (self.reserve_ns if preserve_reserve else 0)
        now = time.monotonic_ns()
        end = AdmittedDeadline(outer_available_end, vector_end_ns, None).command_end(maximum_seconds)
        allowance = min(maximum_seconds, (end - now) / NANOSECONDS)
        if allowance <= 0:
            raise TimeoutError(ERROR_BUDGET)
        return allowance

    def admit(self, required_seconds: float) -> None:
        """Require the entire declared phase plus closure/export reserve before a start."""
        if self.allowance(required_seconds, preserve_reserve=True) < required_seconds:
            raise TimeoutError(ERROR_BUDGET)
