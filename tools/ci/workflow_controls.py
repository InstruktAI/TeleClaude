"""The owned control directories of the native fixture's launches, for the journeys that start platform sessions.

The fixture reads its sidecar configuration once per launch. A journey with one launch points the sidecar at a fresh
directory holding the launch\'s command plan; a journey with several launches in the same window writes the sidecar
once, before any launch, with a pool of directories (each already holding its plan) from which every launching fixture
claims one atomically. Nothing rewrites the sidecar while launches happen, and the original configuration is restored
when the journey ends. Only directories this module created are removed, and never while closure is unproven.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, TypedDict

from tools.ci import workflow_foundation as foundation

PLAN_FILE: Final = "plan.json"
POOL_KEY: Final = "control_directories"
SINGLE_KEY: Final = foundation.CONFIG_CONTROL_DIRECTORY
PLAN_REGISTRY_CONFIG_KEY: Final = "plan_registry"
PLAN_CLAIMS_CONFIG_KEY: Final = "plan_claims"
PLAN_REGISTRY_NAME: Final = "plans.json"
PLAN_CLAIMS_NAME: Final = "claims"
PLAN_SETS_FIELD: Final = "plan_sets"
PLAN_CONTROL_COUNT_FIELD: Final = "plan_control_count"
PLAN_SPARE_COUNT_FIELD: Final = "plan_spare_count"
EMPTY_COMMANDS: Final = "commands"
EMPTY_DIRECTORY_PREFIX: Final = "d"
CLAIM_MARKER: Final = "claimed"
ENCODING: Final = "utf-8"

type Plan = Mapping[str, object]


class Command(TypedDict, total=False):
    """One reviewed public command of a launch\'s plan: static argv, or an argument list written late by the controller."""

    name: str
    argv: list[str]
    argv_from: str
    wait_for: str
    writes: list[Mapping[str, object]]
    cwd: str


class PlanFile(TypedDict, total=False):
    """A launch\'s plan file: its commands in order, and an optional hold of its SessionStart barrier."""

    commands: list[Command]
    barrier_hold_seconds: int


def command(name: str, argv: list[str], gate: str | None = None) -> Command:
    entry = Command(name=name, argv=argv)
    if gate is not None:
        entry["wait_for"] = gate
    return entry


def late(name: str, file_name: str, gate: str) -> Command:
    return Command(name=name, argv_from=file_name, wait_for=gate)


class Controls:
    """The control directories one journey owns beside the profile\'s own fixture setup."""

    def __init__(self, setup: foundation.FixtureSetup, name: str) -> None:
        self.setup = setup
        self.root = setup.control.parent / name
        self.original = setup.configuration.read_text(encoding=ENCODING)
        self.directories: list[Path] = []
        self.registry_path: Path | None = None
        self.claims_path: Path | None = None

    def _write_configuration(self, key: str, value: object) -> None:
        configuration = json.loads(self.original)
        configuration[key] = value
        self.setup.configuration.write_text(json.dumps(configuration), encoding=ENCODING)

    def _prepare(self, plan: Plan | None, directory: Path) -> foundation.FixtureSetup:
        directory.mkdir(parents=True)
        if plan is not None:
            (directory / PLAN_FILE).write_text(json.dumps(plan), encoding=ENCODING)
        self.directories.append(directory)
        return foundation.FixtureSetup(self.setup.executable, self.setup.configuration, directory)

    def single(self, plan: Plan) -> foundation.FixtureSetup:
        """One fresh directory for one launch, with its plan, and the sidecar pointed at it."""
        shutil.rmtree(self.root, ignore_errors=True)
        setup = self._prepare(plan, self.root)
        self._write_configuration(SINGLE_KEY, str(self.root))
        return setup

    def pool(self, plans: Sequence[Plan]) -> list[foundation.FixtureSetup]:
        """A pool of directories, one per plan in the order the launches are planned, claimed atomically by launches."""
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        setups = [self._prepare(plan, self.root / f"d{index}") for index, plan in enumerate(plans)]
        self._write_configuration(POOL_KEY, [str(setup.control) for setup in setups])
        return setups

    def shared_pool(self, plan_sets: Mapping[str, Sequence[Plan]], count: int) -> list[foundation.FixtureSetup]:
        """Create one fixed control pool and shared opaque-key plan registry for the whole flow."""
        self.root.mkdir(parents=True, exist_ok=True)
        registry = self.root / PLAN_REGISTRY_NAME
        claims = self.root / PLAN_CLAIMS_NAME
        if registry.exists() or claims.exists():
            raise FileExistsError(f"shared flow registry already exists at {self.root}")
        claims.mkdir()
        registry_payload = {PLAN_SETS_FIELD: {key: list(plans) for key, plans in plan_sets.items()}}
        registry.write_text(json.dumps(registry_payload), encoding=ENCODING)
        self.registry_path = registry
        self.claims_path = claims
        setups = [self._prepare(None, self.root / f"{EMPTY_DIRECTORY_PREFIX}{index}") for index in range(count)]
        configuration = json.loads(self.original)
        configuration[POOL_KEY] = [str(setup.control) for setup in setups]
        configuration[PLAN_REGISTRY_CONFIG_KEY] = str(registry)
        configuration[PLAN_CLAIMS_CONFIG_KEY] = str(claims)
        configuration[PLAN_CONTROL_COUNT_FIELD] = max(0, count - 2)
        configuration[PLAN_SPARE_COUNT_FIELD] = 2
        self.setup.configuration.write_text(json.dumps(configuration), encoding=ENCODING)
        return setups

    def claimed(self) -> list[Path]:
        """The pool directories a launch has claimed."""
        return [directory for directory in self.directories if (directory / CLAIM_MARKER).exists()]

    def restore(self) -> list[str]:
        """Restore the original sidecar and remove the directories; report what could not be done."""
        failures: list[str] = []
        try:
            self.setup.configuration.write_text(self.original, encoding=ENCODING)
        except OSError as error:
            failures.append(f"sidecar configuration: {type(error).__name__}")
        shutil.rmtree(self.root, ignore_errors=True)
        return failures
