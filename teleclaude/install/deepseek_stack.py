"""Compose and present the DeepSeek stack convergence for operators, agents and the installer."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path

from instrukt_ai_logging import configure_logging

from teleclaude.core.reconciliation.deepseek_fit import (
    Blocker,
    CompatibilityView,
    DeepSeekStackError,
    PackageSource,
    PlannedPackage,
    RequiredPlugin,
    Stack,
)
from teleclaude.core.reconciliation.deepseek_stack import (
    ConvergenceResult,
    GateVerdict,
    SnapshotRef,
    StackDifference,
    StackOutcome,
    UnchangedReason,
    converge_deepseek_stack,
)
from teleclaude.install.deepseek_gate import DeepSeekGate
from teleclaude.install.deepseek_profiles import DeepSeekProfileEffects, harness_home
from teleclaude.install.deepseek_registry import RegistryCompatibilityView

# The plugins TeleClaude's installation puts in every profile: its own hook plugin from the local checkout of the
# plugins repository, and the checkpoint plugin from the registry.
_HOOKS_PLUGIN = "dsh-hooks"
_CHECKPOINT_PLUGIN = "dsh-checkpoint-rewind"
_PLUGINS_DIRECTORY = "plugins"
_LOCAL_REFERENCE_PREFIX = "file:"

EXIT_CONVERGED = 0
EXIT_OPERATION_ERROR = 1
EXIT_ROLLED_BACK = 2
EXIT_ROLLBACK_INCOMPLETE = 3
_OUTCOME_EXIT_STATUS: Mapping[StackOutcome, int] = {
    StackOutcome.UPGRADED: EXIT_CONVERGED,
    StackOutcome.UNCHANGED: EXIT_CONVERGED,
    StackOutcome.ROLLED_BACK: EXIT_ROLLED_BACK,
    StackOutcome.ROLLBACK_INCOMPLETE: EXIT_ROLLBACK_INCOMPLETE,
}

_SCRATCH_PREFIX = "teleclaude-deepseek-stack-"
_LOGGER_NAME = "teleclaude"
_ARGUMENT_DESCRIPTION = "Move the DeepSeek runtime, its TUI and every plugin to the newest mutually compatible set."

_OUTCOME_LINES: Mapping[StackOutcome, str] = {
    StackOutcome.UPGRADED: "DeepSeek stack: upgraded and verified.",
    StackOutcome.UNCHANGED: "DeepSeek stack: unchanged.",
    StackOutcome.ROLLED_BACK: "DeepSeek stack: rolled back; every profile starts as before the run.",
    StackOutcome.ROLLBACK_INCOMPLETE: "DeepSeek stack: ROLLBACK INCOMPLETE; parts of the stack still differ.",
}
_UNCHANGED_REASON_LINES: Mapping[UnchangedReason, str] = {
    UnchangedReason.NO_FITTING_SET: "No newer set fits, or the newest set that fits is already installed.",
    UnchangedReason.RUN_IN_PROGRESS: "Another run is in progress.",
}
_CHANGE_TEMPLATE = "  {subject}: {name} {previous} -> {adopted}"
_RUNTIME_SUBJECT = "runtime"
_ABSENT = "none"
_BLOCKER_TEMPLATE = (
    "  blocked at runtime {candidate}: {package}@{version} requires {requirement} {range}, which it does not satisfy"
)
_BLOCKER_UNPUBLISHED_TEMPLATE = "  blocked at runtime {candidate}: {package} has no published version"
_UNKNOWN_VERSION = "(local)"
_ADVISORY_TEMPLATE = (
    "  advisory: {package}@{version} requires {requirement} {range}; the adopted runtime brings {brought}"
)
_FAILED_STEP_TEMPLATE = "Failed step: {step}"
_FAILED_CHECK_TEMPLATE = "Failed check: {check}"
_FAILURE_DETAIL_TEMPLATE = "Detail: {detail}"
_DIFFERENCE_TEMPLATE = "  still differs: {step} {subject}: {detail}"
_SNAPSHOT_KEPT_TEMPLATE = "The snapshot is kept at {path}."
_OPERATION_ERROR_TEMPLATE = "DeepSeek stack: nothing was changed; {error}"
_NO_DETAIL = "-"


class _ConvergenceEffects:
    """The convergence decision's effects: stack-side, registry-side and gate, composed for one run."""

    def __init__(self, scratch_directory: Path) -> None:
        self._profiles = DeepSeekProfileEffects(scratch_directory)
        self._registry = RegistryCompatibilityView(scratch_directory)
        self._gate = DeepSeekGate(scratch_directory)

    def acquire_run(self) -> AbstractContextManager[bool]:
        return self._profiles.acquire_run()

    def read_stack(self, required: Sequence[RequiredPlugin]) -> Stack:
        return self._profiles.read_stack(required)

    def compatibility_view(self) -> CompatibilityView:
        return self._registry

    def take_snapshot(self, stack: Stack) -> SnapshotRef:
        return self._profiles.take_snapshot(stack)

    def install_runtime(self, version: str) -> None:
        self._profiles.install_runtime(version)

    def apply_profile(self, profile: str, packages: tuple[PlannedPackage, ...]) -> None:
        self._profiles.apply_profile(profile, packages)

    def restore(self, snapshot: SnapshotRef) -> tuple[StackDifference, ...]:
        return self._profiles.restore(snapshot)

    def release_snapshot(self, snapshot: SnapshotRef) -> None:
        self._profiles.release_snapshot(snapshot)

    def run_gate(self, stack: Stack) -> GateVerdict:
        return self._gate.run_gate(stack)


def required_plugins() -> tuple[RequiredPlugin, ...]:
    """The plugins every profile must hold: the hook plugin from the local checkout, the checkpoint plugin from the registry."""
    checkout = harness_home() / _PLUGINS_DIRECTORY / _HOOKS_PLUGIN
    return (
        RequiredPlugin(_HOOKS_PLUGIN, PackageSource.LOCAL_CHECKOUT, _LOCAL_REFERENCE_PREFIX + str(checkout)),
        RequiredPlugin(_CHECKPOINT_PLUGIN, PackageSource.REGISTRY, None),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one convergence, print its report, and return the exit status that names the outcome."""
    argparse.ArgumentParser(description=_ARGUMENT_DESCRIPTION).parse_args(argv)
    configure_logging(_LOGGER_NAME)
    scratch = Path(tempfile.mkdtemp(prefix=_SCRATCH_PREFIX))
    keep_scratch = False
    try:
        result = converge_deepseek_stack(_ConvergenceEffects(scratch), required_plugins())
        keep_scratch = result.retained_snapshot is not None
    except DeepSeekStackError as error:
        print(_OPERATION_ERROR_TEMPLATE.format(error=error))
        return EXIT_OPERATION_ERROR
    finally:
        if not keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    _present(result)
    return _OUTCOME_EXIT_STATUS[result.outcome]


def _present(result: ConvergenceResult) -> None:
    print(_OUTCOME_LINES[result.outcome])
    if result.unchanged_reason is not None:
        print(_UNCHANGED_REASON_LINES[result.unchanged_reason])
    for change in result.changes:
        print(
            _CHANGE_TEMPLATE.format(
                subject=change.profile or _RUNTIME_SUBJECT,
                name=change.name,
                previous=change.previous or _ABSENT,
                adopted=change.adopted or _ABSENT,
            )
        )
    for blocker in result.blockers:
        print(_blocker_line(blocker))
    for advisory in result.advisories:
        print(
            _ADVISORY_TEMPLATE.format(
                package=advisory.package,
                version=advisory.version or _UNKNOWN_VERSION,
                requirement=advisory.requirement_name,
                range=advisory.requirement_range,
                brought=advisory.brought_version,
            )
        )
    if result.failed_step is not None:
        print(_FAILED_STEP_TEMPLATE.format(step=result.failed_step.value))
    if result.failed_check is not None:
        print(_FAILED_CHECK_TEMPLATE.format(check=result.failed_check.value))
    if result.failure_detail is not None:
        print(_FAILURE_DETAIL_TEMPLATE.format(detail=result.failure_detail))
    for difference in result.differences:
        print(
            _DIFFERENCE_TEMPLATE.format(
                step=difference.step.value, subject=difference.subject, detail=difference.detail or _NO_DETAIL
            )
        )
    if result.retained_snapshot is not None:
        print(_SNAPSHOT_KEPT_TEMPLATE.format(path=result.retained_snapshot))


def _blocker_line(blocker: Blocker) -> str:
    if blocker.requirement_name is None or blocker.requirement_range is None:
        return _BLOCKER_UNPUBLISHED_TEMPLATE.format(candidate=blocker.candidate, package=blocker.package)
    return _BLOCKER_TEMPLATE.format(
        candidate=blocker.candidate,
        package=blocker.package,
        version=blocker.failing_version or _UNKNOWN_VERSION,
        requirement=blocker.requirement_name,
        range=blocker.requirement_range,
    )


if __name__ == "__main__":
    raise SystemExit(main())
