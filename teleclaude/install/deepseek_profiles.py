"""Stack-side effects of the DeepSeek convergence: reading, locking, snapshotting, applying, restoring.

Executes only. Which versions to adopt and whether to keep them is the core operation's
decision; every vendor tool runs without terminal input, and the plugin manager's
compatibility exemption is never invoked.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.reconciliation.deepseek_fit import (
    RUNTIME_PACKAGE,
    DeepSeekStackError,
    PackageSource,
    PlannedPackage,
    ProfileStack,
    RequiredPlugin,
    Stack,
    StackPackage,
    registry_reference,
)
from teleclaude.core.reconciliation.deepseek_stack import (
    ConvergenceStep,
    SnapshotRef,
    StackDifference,
)
from teleclaude.install.deepseek_registry import (
    NPM_INSTALL_TIMEOUT_SECONDS,
    installed_runtime_directory,
    npm_global_prefix,
    read_manifest,
    run_npm,
    string_field,
    string_mapping,
)

logger = get_logger(__name__)

_DSH_HOME_VARIABLE = "DSH_HOME"
_DEFAULT_HOME_DIRECTORY = ".dsh"
_PROFILES_DIRECTORY = "profiles"
_MANIFEST_FILE = "package.json"
_PNPM_LOCK_FILE = "pnpm-lock.yaml"
_EXEMPTION_FILE = "compatibility.json"
_RESTORE_COMPARED_FILES = (_MANIFEST_FILE, _PNPM_LOCK_FILE, _EXEMPTION_FILE)
_NODE_MODULES = "node_modules"
_DEPENDENCIES_FIELD = "dependencies"
_VERSION_FIELD = "version"
_BIN_NAME = "dsh"
_LOCAL_REFERENCE_PREFIX = "file:"
_EXECUTABLES_DIRECTORY = "bin"
_PLUGIN_COMMAND = "plugin"
_PROFILE_FLAG = "--profile"
_ADD_COMMAND = "add"
_NPM_INSTALL = "install"
_NPM_UNINSTALL = "uninstall"
_NPM_GLOBAL_FLAG = "-g"
_APPLY_TIMEOUT_SECONDS = 900
_SNAPSHOT_DIRECTORY = "snapshot"
_SNAPSHOT_PROFILES_DIRECTORY = "profiles"
_LOCK_DIGEST_CHARS = 16
_LOCK_FILE_TEMPLATE = "teleclaude-deepseek-stack-{digest}.lock"
_LOCK_FILE_MODE = 0o600
_ENCODING = "utf-8"
_DETAIL_TAIL_CHARS = 600

_PLUGIN_ADD_FAILURE_TEMPLATE = "Adding {packages} to profile {profile} failed: {detail}"
_PLUGIN_ADD_TIMEOUT_TEMPLATE = "Adding {packages} to profile {profile} timed out after {seconds} seconds"
_PLUGIN_ADD_UNAVAILABLE_TEMPLATE = "Cannot run the runtime executable {path}: {error}"
_RUNTIME_INSTALL_FAILURE_TEMPLATE = "Installing {spec} globally failed: {detail}"
_RUNTIME_UNINSTALL_FAILURE_TEMPLATE = "Removing {name} globally failed: {detail}"
_SNAPSHOT_FAILURE_TEMPLATE = "Cannot snapshot profile {profile}: {error}"
_FILE_DIFFERS_TEMPLATE = "{file} differs from the snapshot"
_RUNTIME_DIFFERS_TEMPLATE = "installed version {installed} differs from the snapshot's {recorded}"
_RUNTIME_ABSENT_LABEL = "none"
_ARGUMENT_SEPARATOR = " "
_LOG_RESTORE_STEP = "DeepSeek stack restore step failed"


def harness_home() -> Path:
    """The vendor's harness home: ``$DSH_HOME`` when set and not blank, else ``~/.dsh``."""
    configured = os.environ.get(_DSH_HOME_VARIABLE, "")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    if configured.strip():
        return Path(configured)
    return Path.home() / _DEFAULT_HOME_DIRECTORY


def dsh_executable() -> Path:
    """The runtime's executable under npm's global prefix, so a fresh install needs no ``PATH`` refresh."""
    return npm_global_prefix() / _EXECUTABLES_DIRECTORY / _BIN_NAME


class DeepSeekProfileEffects:
    """Reads, locks, snapshots, applies to and restores the machine's DeepSeek stack."""

    def __init__(self, scratch_directory: Path) -> None:
        self._scratch_directory = scratch_directory

    @contextmanager
    def acquire_run(self) -> Iterator[bool]:
        """Hold one run per harness home; yields ``False`` when another run already holds it."""
        digest = hashlib.sha256(str(harness_home().resolve()).encode(_ENCODING)).hexdigest()[:_LOCK_DIGEST_CHARS]
        path = Path(tempfile.gettempdir()) / _LOCK_FILE_TEMPLATE.format(digest=digest)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, _LOCK_FILE_MODE)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            os.close(descriptor)

    def read_stack(self, required: Sequence[RequiredPlugin]) -> Stack:
        """The installed runtime version and every profile's packages as their manifests declare them."""
        return Stack(_installed_runtime_version(), _read_profiles(), tuple(required))

    def take_snapshot(self, stack: Stack) -> SnapshotRef:
        """Copy every profile directory as found and record the installed runtime version."""
        snapshot = self._scratch_directory / _SNAPSHOT_DIRECTORY
        for profile in stack.profiles:
            try:
                shutil.copytree(
                    _profile_directory(profile.name),
                    snapshot / _SNAPSHOT_PROFILES_DIRECTORY / profile.name,
                    symlinks=True,
                )
            except (OSError, shutil.Error) as error:
                raise DeepSeekStackError(
                    _SNAPSHOT_FAILURE_TEMPLATE.format(profile=profile.name, error=error)
                ) from error
        return SnapshotRef(str(snapshot), stack.runtime_version)

    def install_runtime(self, version: str) -> None:
        """Install the exact runtime version globally."""
        spec = registry_reference(RUNTIME_PACKAGE, version)
        result = run_npm((_NPM_INSTALL, _NPM_GLOBAL_FLAG, spec), timeout_seconds=NPM_INSTALL_TIMEOUT_SECONDS)
        if result.returncode != 0:
            raise DeepSeekStackError(_RUNTIME_INSTALL_FAILURE_TEMPLATE.format(spec=spec, detail=result.detail))

    def apply_profile(self, profile: str, packages: tuple[PlannedPackage, ...]) -> None:
        """Add each package to the profile through the runtime's plugin manager, at its exact reference."""
        references = tuple(package.reference for package in packages)
        label = _ARGUMENT_SEPARATOR.join(references)
        executable = dsh_executable()
        try:
            # The runtime's plugin manager owns profile installation (pnpm underneath); no Python API exists.
            # stdin is closed so no vendor prompt, a compatibility exemption included, can be accepted.
            completed = subprocess.run(
                (str(executable), _PLUGIN_COMMAND, _PROFILE_FLAG, profile, _ADD_COMMAND, *references),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                text=True,
                timeout=_APPLY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise DeepSeekStackError(
                _PLUGIN_ADD_TIMEOUT_TEMPLATE.format(packages=label, profile=profile, seconds=_APPLY_TIMEOUT_SECONDS)
            ) from error
        except OSError as error:
            raise DeepSeekStackError(_PLUGIN_ADD_UNAVAILABLE_TEMPLATE.format(path=executable, error=error)) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-_DETAIL_TAIL_CHARS:]
            raise DeepSeekStackError(
                _PLUGIN_ADD_FAILURE_TEMPLATE.format(packages=label, profile=profile, detail=detail)
            )

    def restore(self, snapshot: SnapshotRef) -> tuple[StackDifference, ...]:
        """Put the runtime and every profile directory back as snapshotted; return what still differs."""
        differences = [*self._restore_runtime(snapshot), *self._restore_profiles(snapshot)]
        return tuple(differences)

    def release_snapshot(self, snapshot: SnapshotRef) -> None:
        """Remove the snapshot copy; the entry point removes the rest of the scratch area."""
        shutil.rmtree(snapshot.location, ignore_errors=True)

    def _restore_runtime(self, snapshot: SnapshotRef) -> list[StackDifference]:
        try:
            if _installed_runtime_version() != snapshot.runtime_version:
                _set_runtime(snapshot.runtime_version)
            installed = _installed_runtime_version()
        except DeepSeekStackError as error:
            logger.error(_LOG_RESTORE_STEP, step=ConvergenceStep.RUNTIME_RESTORE, error=str(error))
            return [StackDifference(ConvergenceStep.RUNTIME_RESTORE, RUNTIME_PACKAGE, str(error))]
        if installed == snapshot.runtime_version:
            return []
        detail = _RUNTIME_DIFFERS_TEMPLATE.format(
            installed=installed or _RUNTIME_ABSENT_LABEL, recorded=snapshot.runtime_version or _RUNTIME_ABSENT_LABEL
        )
        return [StackDifference(ConvergenceStep.RUNTIME_RESTORE, RUNTIME_PACKAGE, detail)]

    def _restore_profiles(self, snapshot: SnapshotRef) -> list[StackDifference]:
        differences: list[StackDifference] = []
        snapshot_profiles = Path(snapshot.location) / _SNAPSHOT_PROFILES_DIRECTORY
        if not snapshot_profiles.is_dir():
            return differences
        for recorded in sorted(snapshot_profiles.iterdir()):
            target = _profile_directory(recorded.name)
            try:
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(recorded, target, symlinks=True)
            except (OSError, shutil.Error) as error:
                logger.error(
                    _LOG_RESTORE_STEP, step=ConvergenceStep.PROFILE_RESTORE, profile=recorded.name, error=str(error)
                )
                differences.append(StackDifference(ConvergenceStep.PROFILE_RESTORE, recorded.name, str(error)))
                continue
            differences.extend(
                StackDifference(
                    ConvergenceStep.PROFILE_RESTORE, recorded.name, _FILE_DIFFERS_TEMPLATE.format(file=file_name)
                )
                for file_name in _RESTORE_COMPARED_FILES
                if _file_bytes(recorded / file_name) != _file_bytes(target / file_name)
            )
        return differences


def _set_runtime(version: str | None) -> None:
    """Reinstall the recorded runtime version, or remove the runtime when none was installed."""
    if version is not None:
        spec = registry_reference(RUNTIME_PACKAGE, version)
        result = run_npm((_NPM_INSTALL, _NPM_GLOBAL_FLAG, spec), timeout_seconds=NPM_INSTALL_TIMEOUT_SECONDS)
        if result.returncode != 0:
            raise DeepSeekStackError(_RUNTIME_INSTALL_FAILURE_TEMPLATE.format(spec=spec, detail=result.detail))
        return
    result = run_npm((_NPM_UNINSTALL, _NPM_GLOBAL_FLAG, RUNTIME_PACKAGE), timeout_seconds=NPM_INSTALL_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise DeepSeekStackError(_RUNTIME_UNINSTALL_FAILURE_TEMPLATE.format(name=RUNTIME_PACKAGE, detail=result.detail))


def _file_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _profile_directory(name: str) -> Path:
    return harness_home() / _PROFILES_DIRECTORY / name


def _installed_runtime_version() -> str | None:
    manifest_path = installed_runtime_directory() / _MANIFEST_FILE
    if not manifest_path.is_file():
        return None
    return string_field(read_manifest(manifest_path), _VERSION_FIELD, str(manifest_path))


def _read_profiles() -> tuple[ProfileStack, ...]:
    profiles_directory = harness_home() / _PROFILES_DIRECTORY
    if not profiles_directory.is_dir():
        return ()
    profiles: list[ProfileStack] = []
    for directory in sorted(profiles_directory.iterdir()):
        manifest_path = directory / _MANIFEST_FILE
        if not manifest_path.is_file():
            continue
        dependencies = string_mapping(read_manifest(manifest_path).get(_DEPENDENCIES_FIELD), str(manifest_path))
        profiles.append(
            ProfileStack(
                directory.name,
                tuple(
                    StackPackage(name, _source_of(reference), reference, _installed_version(directory, name))
                    for name, reference in sorted(dependencies.items())
                ),
            )
        )
    return tuple(profiles)


def _source_of(reference: str) -> PackageSource:
    return PackageSource.LOCAL_CHECKOUT if reference.startswith(_LOCAL_REFERENCE_PREFIX) else PackageSource.REGISTRY


def _installed_version(profile_directory: Path, name: str) -> str | None:
    manifest_path = profile_directory / _NODE_MODULES / name / _MANIFEST_FILE
    if not manifest_path.is_file():
        return None
    return string_field(read_manifest(manifest_path), _VERSION_FIELD, str(manifest_path))
