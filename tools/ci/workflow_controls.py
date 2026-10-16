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
CLAIM_MARKER: Final = "claimed"
ENCODING: Final = "utf-8"

type Plan = Mapping[str, object]


class Command(TypedDict, total=False):
    """One reviewed public command of a launch\'s plan: static argv, or an argument list written late by the controller."""

    name: str
    argv: list[str]
    argv_from: str
    wait_for: str


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

    def _write_configuration(self, key: str, value: object) -> None:
        configuration = json.loads(self.original)
        configuration[key] = value
        self.setup.configuration.write_text(json.dumps(configuration), encoding=ENCODING)

    def _prepare(self, plan: Plan, directory: Path) -> foundation.FixtureSetup:
        directory.mkdir(parents=True)
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
