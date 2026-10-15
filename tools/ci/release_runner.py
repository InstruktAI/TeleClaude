"""Install and operate the repository's opt-in Tart Runner Fleet controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from instrukt_ai_logging import configure_logging, get_logger
from pydantic import BaseModel, ConfigDict, ValidationError

_LOCK_PATH = Path(__file__).with_name("release_runner.lock.json")
_ROOT_NAME = "tart-runner-fleet"
_RELEASES_NAME = "releases"
_STATE_NAME = "state"
_GUEST_ASSETS_NAME = "guest-assets"
_LAUNCHD_NAME = "launchd"
_AUTHORITY_GENERATION_NAME = "authority.plist"
_CANONICAL_PLIST = "com.vitalyiegorov.tart-runner-fleet.plist"
_OBSERVE_CANONICAL_PLIST = "com.vitalyiegorov.tart-runner-fleet.observe.plist"
_AUTHORITY_LABEL = "com.vitalyiegorov.tart-runner-fleet.authority"
_OBSERVE_PLIST = "com.vitalyiegorov.tart-runner-fleet.plist"
_SHADOW_PLIST = "com.vitalyiegorov.tart-runner-fleet.shadow.plist"
_CANARY_PLIST = "com.vitalyiegorov.tart-runner-fleet.canary.plist"
_AUTHORITY_PLIST = "com.vitalyiegorov.tart-runner-fleet.authority.plist"
_OBSERVE_LABEL = "com.vitalyiegorov.tart-runner-fleet"
_SHADOW_LABEL = "com.vitalyiegorov.tart-runner-fleet.shadow"
_CANARY_LABEL = "com.vitalyiegorov.tart-runner-fleet.canary"
_RUNNER_BINARY = "fleet"
_RENDERER_BINARY = "render-launchd.sh"
_HELPER_BINARY = "tart-runner-fleet-bootstrap-linux-arm64"
_CONFIG_NAME = "fleet.json"
_STATUS_OUTPUT_OPTION = "--output"
_JSON_FORMAT = "json"
_STATUS_COMMAND = "status"
_READY_OPTION = "--require-ready"
_CONFIG_COMMAND = "config"
_VALIDATE_COMMAND = "validate"
_AUTHORITY_MODE = "authority"
_OBSERVE_MODE = "observe"
_SHADOW_MODE = "shadow"
_CANARY_MODE = "canary"
_INSTALL_MODE = 0o700
_PRIVATE_MODE = 0o600
_FILE_READ_MODE = "rb"
_FILE_WRITE_MODE = "wb"
_COPY_CHUNK_SIZE = 1024 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 120
_COMMAND_TIMEOUT_SECONDS = 30
_EMPTY = ""
_NEWLINE = "\n"
_UNSUPPORTED_HOST = "release-runner controls require an Apple Silicon macOS host"
_LOCK_INVALID = "the release runner lock file is invalid"
_ASSET_INVALID = "a pinned release asset has an invalid URL or digest"
_ASSET_DIGEST_INVALID = "a downloaded release asset failed its pinned SHA-256 check"
_ASSET_PRESENT_INVALID = "an installed release asset differs from its pinned digest"
_ARCHIVE_INVALID = "the pinned Fleet archive contains an unsafe member"
_CONFIG_MISSING = "the private Fleet configuration is missing or is not a regular file"
_CONFIG_PERMISSIONS = "the private Fleet configuration must not be readable by group or other users"
_SERVICE_CONFLICT = "the canonical Fleet LaunchAgent differs; preserve it and review the installed generation"
_SERVICE_MISSING = "the dedicated Fleet LaunchAgent is not installed"
_SERVICE_UPDATE_FAILED = "the new Fleet generation failed readiness; the previous generation was restored"
_SERVICE_ROLLBACK_FAILED = "the new Fleet generation failed and the previous generation could not be restored"
_STATUS_CALL = "fleet status"
_VALIDATE_CALL = "fleet config validate"
_START_CALL = "launchctl bootstrap"
_KICKSTART_CALL = "launchctl kickstart"
_STOP_CALL = "launchctl bootout"
_RENDER_CALL = "Fleet launchd renderer"
_PROCESS_FAILED = "{name} failed with exit code {exit_code}"
_OPERATION_FAILED_EVENT = "release_runner_operation_failed"
_LOG_APPLICATION_NAME = "teleclaude"
_UTF8 = "utf-8"
_HTTPS = "https://"
_DARWIN = "darwin"
_ARM64 = "arm64"
_LIBRARY = "Library"
_APPLICATION_SUPPORT = "Application Support"
_LAUNCH_AGENTS = "LaunchAgents"
_USER_AGENT_HEADER = "User-Agent"
_USER_AGENT = "TeleClaude-release-runner"
_RENDER_TEMP_PREFIX = "authority."
_RENDER_TEMP_SUFFIX = ".plist"
_UNPACKED_DIRECTORY = "unpacked"
_STAGING_PREFIX = "{version}."
_STATUS_MESSAGE = "Fleet {mode} service stopped"
_SOCKET_FILENAME = "fleetd.sock"
_SHADOW_SOCKET_FILENAME = "fleet-shadow.sock"
_CANARY_SOCKET_FILENAME = "fleet-canary.sock"
_SERVICE_DOMAIN = "gui/{uid}"
_SERVICE_LABEL = "{domain}/{label}"
_ENDPOINT_PREFIX = "unix://"
_ENDPOINT_OPTION = "--endpoint"
_LAUNCHCTL = "/bin/launchctl"
_PLUTIL = "/usr/bin/plutil"
_PLUTIL_LINT = "-lint"
_LAUNCHCTL_PRINT = "print"
_LAUNCHCTL_BOOTSTRAP = "bootstrap"
_LAUNCHCTL_KICKSTART = "kickstart"
_LAUNCHCTL_BOOTOUT = "bootout"
_ACTION_ARGUMENT = "operation"
_ACTION_CHOICES = ("install", "start", "stop", "status")
_OPTION_PREFIX = "--"
_MODE_ARGUMENT = "mode"
_CANARY_SCOPE_ARGUMENT = "canary_scope"
_CANARY_PROFILE_ARGUMENT = "canary_profile"
_CANARY_SCOPE_OPTION = "--canary-scope"
_CANARY_PROFILE_OPTION = "--canary-profile"
_NO_CANARY_SELECTORS = "canary scope/profile are accepted only in canary mode"
_CANARY_SELECTORS_REQUIRED = "canary mode requires both canary scope and profile"
_TAR_READ_MODE: Literal["r:gz"] = "r:gz"
_TAR_DATA_FILTER: Literal["data"] = "data"
_PARENT_PATH_SEGMENT = ".."
_CHECKSUM_LINE_SPLIT = 1
_CHECKSUM_FILENAME_PREFIX = "*"
_LINUX_IMAGE_PREFIX = "ghcr.io/cirruslabs/ubuntu"
_LINUX_IMAGE_DIGEST_MARKER = "@sha256:"
_SHA256_LENGTH = 64
_LOCK_MODEL_CONFIG = ConfigDict(extra="forbid", strict=True)
logger = get_logger(__name__)


class _LockedAsset(BaseModel):
    """Checksum-pinned upstream release asset metadata."""

    model_config = _LOCK_MODEL_CONFIG

    filename: str
    url: str
    sha256: str
    size_bytes: int


class _LockedFleet(BaseModel):
    """Pinned Fleet release and guest bootstrap asset."""

    model_config = _LOCK_MODEL_CONFIG

    version: str
    commit: str
    release_archive: _LockedAsset
    checksums: _LockedAsset
    linux_bootstrap: _LockedAsset


class _LockedLinuxBaseAsset(BaseModel):
    """Pinned Linux image source and guest runner inputs."""

    model_config = _LOCK_MODEL_CONFIG

    version: str
    url: str
    sha256: str
    size_bytes: int


class _LockedLinuxBase(BaseModel):
    """Immutable Linux guest image declaration and qualification inputs."""

    model_config = _LOCK_MODEL_CONFIG

    source_image: str
    architecture: str
    distribution: str
    runner: _LockedLinuxBaseAsset
    fleet_bootstrap_path: str
    promotion: str


class _RunnerLockDocument(BaseModel):
    """Validated top-level runner lock document."""

    model_config = _LOCK_MODEL_CONFIG

    schema_version: Literal[1]
    fleet: _LockedFleet
    linux_base: _LockedLinuxBase


class Operation(StrEnum):
    """Supported release runner operator actions."""

    INSTALL = "install"
    START = "start"
    STOP = "stop"
    STATUS = "status"


class ControllerMode(StrEnum):
    """Vendor-supported Fleet controller rollout modes."""

    OBSERVE = _OBSERVE_MODE
    SHADOW = _SHADOW_MODE
    CANARY = _CANARY_MODE
    AUTHORITY = _AUTHORITY_MODE


_MODE_PLISTS = {
    ControllerMode.OBSERVE: _OBSERVE_PLIST,
    ControllerMode.SHADOW: _SHADOW_PLIST,
    ControllerMode.CANARY: _CANARY_PLIST,
    ControllerMode.AUTHORITY: _AUTHORITY_PLIST,
}
_MODE_CANONICAL_PLISTS = {
    ControllerMode.OBSERVE: _OBSERVE_CANONICAL_PLIST,
    ControllerMode.SHADOW: _SHADOW_PLIST,
    ControllerMode.CANARY: _CANARY_PLIST,
    ControllerMode.AUTHORITY: _CANONICAL_PLIST,
}
_MODE_GENERATION_NAMES = {
    ControllerMode.OBSERVE: _OBSERVE_PLIST,
    ControllerMode.SHADOW: _SHADOW_PLIST,
    ControllerMode.CANARY: _CANARY_PLIST,
    ControllerMode.AUTHORITY: _AUTHORITY_GENERATION_NAME,
}
_MODE_LABELS = {
    ControllerMode.OBSERVE: _OBSERVE_LABEL,
    ControllerMode.SHADOW: _SHADOW_LABEL,
    ControllerMode.CANARY: _CANARY_LABEL,
    ControllerMode.AUTHORITY: _AUTHORITY_LABEL,
}
_MODE_SOCKETS = {
    ControllerMode.OBSERVE: _SOCKET_FILENAME,
    ControllerMode.SHADOW: _SHADOW_SOCKET_FILENAME,
    ControllerMode.CANARY: _CANARY_SOCKET_FILENAME,
    ControllerMode.AUTHORITY: _SOCKET_FILENAME,
}


@dataclass(frozen=True)
class Asset:
    """A pinned downloadable release asset."""

    url: str
    sha256: str
    size_bytes: int
    filename: str


@dataclass(frozen=True)
class FleetLock:
    """Verified deployment inputs read from the checked-in lock file."""

    version: str
    archive: Asset
    checksums: Asset
    helper: Asset


@dataclass(frozen=True)
class RunnerOperationRequest:
    """Validated mode inputs passed from the CLI to the operation dispatcher."""

    mode: ControllerMode
    canary_scope: str | None
    canary_profile: str | None


def _read_lock() -> FleetLock:
    try:
        raw: object = json.loads(_LOCK_PATH.read_text(encoding=_UTF8))
        document = _RunnerLockDocument.model_validate(raw)
    except (ValidationError, json.JSONDecodeError, OSError) as exc:
        raise ValueError(_LOCK_INVALID) from exc
    fleet = document.fleet
    result = FleetLock(
        version=fleet.version,
        archive=Asset(
            url=fleet.release_archive.url,
            sha256=fleet.release_archive.sha256,
            size_bytes=fleet.release_archive.size_bytes,
            filename=fleet.release_archive.filename,
        ),
        checksums=Asset(
            url=fleet.checksums.url,
            sha256=fleet.checksums.sha256,
            size_bytes=fleet.checksums.size_bytes,
            filename=fleet.checksums.filename,
        ),
        helper=Asset(
            url=fleet.linux_bootstrap.url,
            sha256=fleet.linux_bootstrap.sha256,
            size_bytes=fleet.linux_bootstrap.size_bytes,
            filename=fleet.linux_bootstrap.filename,
        ),
    )
    linux_runner = document.linux_base.runner
    linux_runner_asset = Asset(
        url=linux_runner.url,
        sha256=linux_runner.sha256,
        size_bytes=linux_runner.size_bytes,
        filename=linux_runner.version,
    )
    for asset in (result.archive, result.checksums, result.helper, linux_runner_asset):
        if not asset.url.startswith(_HTTPS) or len(asset.sha256) != _SHA256_LENGTH or asset.size_bytes < 1:
            raise ValueError(_ASSET_INVALID)
        try:
            int(asset.sha256, 16)
        except ValueError as exc:
            raise ValueError(_ASSET_INVALID) from exc
    source_image = document.linux_base.source_image
    image_digest = source_image.partition(_LINUX_IMAGE_DIGEST_MARKER)[2]
    if (
        not source_image.startswith(_LINUX_IMAGE_PREFIX + _LINUX_IMAGE_DIGEST_MARKER)
        or len(image_digest) != _SHA256_LENGTH
    ):
        raise ValueError(_ASSET_INVALID)
    try:
        int(image_digest, 16)
    except ValueError as exc:
        raise ValueError(_ASSET_INVALID) from exc
    return result


def _host_root() -> Path:
    if sys.platform != _DARWIN or os.uname().machine != _ARM64:
        raise RuntimeError(_UNSUPPORTED_HOST)
    home = Path.home().resolve(strict=True)
    root = home / _LIBRARY / _APPLICATION_SUPPORT / _ROOT_NAME
    root.mkdir(mode=_INSTALL_MODE, parents=True, exist_ok=True)
    root.chmod(_INSTALL_MODE)
    return root


def _download(asset: Asset, destination: Path) -> None:
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(asset.url, headers={_USER_AGENT_HEADER: _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
        with destination.open(_FILE_WRITE_MODE) as output:
            while chunk := response.read(_COPY_CHUNK_SIZE):
                size += len(chunk)
                if size > asset.size_bytes:
                    destination.unlink(missing_ok=True)
                    raise RuntimeError(_ASSET_DIGEST_INVALID)
                digest.update(chunk)
                output.write(chunk)
    if size != asset.size_bytes or digest.hexdigest() != asset.sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError(_ASSET_DIGEST_INVALID)
    destination.chmod(_PRIVATE_MODE)


def _verify_existing(path: Path, asset: Asset) -> None:
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != asset.sha256:
        raise RuntimeError(_ASSET_PRESENT_INVALID)


def _verify_release_checksums(path: Path, lock: FleetLock) -> None:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding=_UTF8).splitlines():
        parts = line.split(maxsplit=_CHECKSUM_LINE_SPLIT)
        if not parts:
            continue
        if len(parts) != 2:
            raise RuntimeError(_ASSET_INVALID)
        filename = parts[1].removeprefix(_CHECKSUM_FILENAME_PREFIX)
        checksums[filename] = parts[0]
    for asset in (lock.archive, lock.helper):
        if checksums.get(asset.filename) != asset.sha256:
            raise RuntimeError(_ASSET_DIGEST_INVALID)


def _extract_archive(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, mode=_TAR_READ_MODE) as archive:
        members = archive.getmembers()
        if not members or any(
            Path(member.name).is_absolute() or _PARENT_PATH_SEGMENT in Path(member.name).parts for member in members
        ):
            raise RuntimeError(_ARCHIVE_INVALID)
        archive.extractall(destination, members=members, filter=_TAR_DATA_FILTER)


def _run(argv: tuple[str, ...], *, name: str, capture: bool = False) -> str:
    # Fleet, its pinned renderer, launchctl and plutil expose these contracts through executables, not Python APIs.
    result = subprocess.run(
        argv,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
        encoding=_UTF8,
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(_PROCESS_FAILED.format(name=name, exit_code=result.returncode))
    return result.stdout or _EMPTY if capture else _EMPTY


def install() -> None:
    """Install the pinned Fleet release and its Linux guest bootstrap helper."""
    lock = _read_lock()
    root = _host_root()
    releases = root / _RELEASES_NAME
    guest_assets = root / _GUEST_ASSETS_NAME
    releases.mkdir(mode=_INSTALL_MODE, exist_ok=True)
    guest_assets.mkdir(mode=_INSTALL_MODE, exist_ok=True)
    release = releases / lock.version
    helper = guest_assets / _HELPER_BINARY
    if release.exists():
        if (
            release.is_symlink()
            or not (release / _RUNNER_BINARY).is_file()
            or not (release / _RENDERER_BINARY).is_file()
        ):
            raise RuntimeError(_ASSET_PRESENT_INVALID)
        _verify_existing(release / lock.archive.filename, lock.archive)
        _verify_existing(release / lock.checksums.filename, lock.checksums)
        _verify_release_checksums(release / lock.checksums.filename, lock)
        _verify_existing(helper, lock.helper)
        return
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        staging = Path(temporary)
        archive_path = staging / lock.archive.filename
        checksums_path = staging / lock.checksums.filename
        helper_path = staging / lock.helper.filename
        _download(lock.archive, archive_path)
        _download(lock.checksums, checksums_path)
        _download(lock.helper, helper_path)
        _verify_release_checksums(checksums_path, lock)
        unpacked = staging / _UNPACKED_DIRECTORY
        unpacked.mkdir(mode=_INSTALL_MODE)
        _extract_archive(archive_path, unpacked)
        binary = unpacked / _RUNNER_BINARY
        renderer = unpacked / _RENDERER_BINARY
        if not binary.is_file() or not renderer.is_file():
            raise RuntimeError(_ASSET_INVALID)
        _verify_existing(archive_path, lock.archive)
        helper_descriptor, helper_temporary = tempfile.mkstemp(prefix=_HELPER_BINARY, dir=guest_assets)
        with (
            os.fdopen(helper_descriptor, _FILE_WRITE_MODE) as helper_output,
            helper_path.open(_FILE_READ_MODE) as source,
        ):
            shutil.copyfileobj(source, helper_output)
        helper_staging = Path(helper_temporary)
        helper_staging.chmod(_INSTALL_MODE)
        helper_staging.replace(helper)
        final_staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX.format(version=lock.version), dir=releases))
        try:
            shutil.copytree(unpacked, final_staging, dirs_exist_ok=True)
            shutil.copy2(archive_path, final_staging / lock.archive.filename)
            shutil.copy2(checksums_path, final_staging / lock.checksums.filename)
            (final_staging / _RUNNER_BINARY).chmod(_INSTALL_MODE)
            (final_staging / _RENDERER_BINARY).chmod(_INSTALL_MODE)
            final_staging.rename(release)
        except BaseException:
            shutil.rmtree(final_staging, ignore_errors=True)
            raise


def _installed(lock: FleetLock, mode: ControllerMode = ControllerMode.AUTHORITY) -> tuple[Path, Path, Path]:
    root = _host_root()
    release = root / _RELEASES_NAME / lock.version
    state = root / _STATE_NAME
    plist = root / _LAUNCHD_NAME / lock.version / _MODE_GENERATION_NAMES[mode]
    if not release.is_dir():
        raise RuntimeError(_ASSET_PRESENT_INVALID)
    state.mkdir(mode=_INSTALL_MODE, parents=True, exist_ok=True)
    return release, state, plist


def _configuration(release: Path, state: Path) -> Path:
    config = state / _CONFIG_NAME
    if config.is_symlink() or not config.is_file():
        raise RuntimeError(_CONFIG_MISSING)
    if config.stat().st_mode & 0o077:
        raise RuntimeError(_CONFIG_PERMISSIONS)
    _run((str(release / _RUNNER_BINARY), _CONFIG_COMMAND, _VALIDATE_COMMAND, str(config)), name=_VALIDATE_CALL)
    return config


def _render(
    release: Path,
    state: Path,
    plist: Path,
    mode: ControllerMode,
    canary_scope: str | None = None,
    canary_profile: str | None = None,
) -> None:
    plist.parent.mkdir(mode=_INSTALL_MODE, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=_RENDER_TEMP_PREFIX, suffix=_RENDER_TEMP_SUFFIX, dir=plist.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        arguments: tuple[str, ...] = (
            str(release / _RENDERER_BINARY),
            mode.value,
            str(release),
            str(state),
            str(temporary),
        )
        if mode is ControllerMode.CANARY:
            if not canary_scope or not canary_profile:
                raise ValueError(_CANARY_SELECTORS_REQUIRED)
            arguments = (*arguments, canary_scope, canary_profile)
        elif canary_scope is not None or canary_profile is not None:
            raise ValueError(_NO_CANARY_SELECTORS)
        _run(arguments, name=_RENDER_CALL)
        _run((_PLUTIL, _PLUTIL_LINT, str(temporary)), name=_RENDER_CALL)
        temporary.chmod(_PRIVATE_MODE)
        if plist.exists():
            if plist.is_symlink() or not plist.is_file() or plist.read_bytes() != temporary.read_bytes():
                raise RuntimeError(_SERVICE_CONFLICT)
            return
        temporary.replace(plist)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical_generation(root: Path, canonical: Path, mode: ControllerMode) -> str | None:
    if not canonical.exists():
        return None
    if canonical.is_symlink() or not canonical.is_file():
        raise RuntimeError(_SERVICE_CONFLICT)
    content = canonical.read_bytes()
    generations = root / _LAUNCHD_NAME
    if not generations.is_dir():
        raise RuntimeError(_SERVICE_CONFLICT)
    for generation in generations.iterdir():
        candidate = generation / _MODE_GENERATION_NAMES[mode]
        if generation.is_dir() and not generation.is_symlink() and candidate.is_file() and not candidate.is_symlink():
            if candidate.read_bytes() == content:
                return generation.name
    raise RuntimeError(_SERVICE_CONFLICT)


def _service_label(mode: ControllerMode) -> str:
    return _SERVICE_LABEL.format(
        domain=_SERVICE_DOMAIN.format(uid=os.getuid()),
        label=_MODE_LABELS[mode],
    )


def _service_loaded(label: str) -> bool:
    # launchctl is macOS's supported service-manager interface; it has no Python API.
    result = subprocess.run(
        (_LAUNCHCTL, _LAUNCHCTL_PRINT, label),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _replace_canonical(plist: Path, canonical: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=_CANONICAL_PLIST, dir=canonical.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(plist, temporary)
        temporary.chmod(_PRIVATE_MODE)
        temporary.replace(canonical)
    finally:
        temporary.unlink(missing_ok=True)


def _launch_generation(
    release: Path, domain: str, label: str, canonical: Path, state: Path, mode: ControllerMode
) -> None:
    _run((_LAUNCHCTL, _LAUNCHCTL_BOOTSTRAP, domain, str(canonical)), name=_START_CALL)
    _run((_LAUNCHCTL, _LAUNCHCTL_KICKSTART, label), name=_KICKSTART_CALL)
    _run(
        (
            str(release / _RUNNER_BINARY),
            _STATUS_COMMAND,
            _READY_OPTION,
            _STATUS_OUTPUT_OPTION,
            _JSON_FORMAT,
            _ENDPOINT_OPTION,
            _ENDPOINT_PREFIX + str(state / _MODE_SOCKETS[mode]),
        ),
        name=_STATUS_CALL,
        capture=True,
    )


def _restore_generation(
    root: Path,
    previous_version: str | None,
    previous_plist: bytes | None,
    canonical: Path,
    domain: str,
    label: str,
    state: Path,
    mode: ControllerMode,
) -> None:
    if _service_loaded(label):
        _run((_LAUNCHCTL, _LAUNCHCTL_BOOTOUT, label), name=_STOP_CALL)
    if previous_version is None or previous_plist is None:
        canonical.unlink(missing_ok=True)
        return
    generation_plist = root / _LAUNCHD_NAME / previous_version / _MODE_GENERATION_NAMES[mode]
    if not generation_plist.is_file() or generation_plist.read_bytes() != previous_plist:
        raise RuntimeError(_SERVICE_ROLLBACK_FAILED)
    _replace_canonical(generation_plist, canonical)
    _launch_generation(
        root / _RELEASES_NAME / previous_version,
        domain,
        label,
        canonical,
        state,
        mode,
    )


def start(
    mode: ControllerMode = ControllerMode.AUTHORITY,
    canary_scope: str | None = None,
    canary_profile: str | None = None,
) -> None:
    """Load one vendor-supported Fleet rollout service after validation."""
    lock = _read_lock()
    root = _host_root()
    release, state, plist = _installed(lock, mode)
    _configuration(release, state)
    _render(release, state, plist, mode, canary_scope, canary_profile)
    canonical = Path.home() / _LIBRARY / _LAUNCH_AGENTS / _MODE_CANONICAL_PLISTS[mode]
    canonical.parent.mkdir(mode=_INSTALL_MODE, parents=True, exist_ok=True)
    previous_version = _canonical_generation(root, canonical, mode)
    previous_plist = canonical.read_bytes() if previous_version is not None else None
    domain = _SERVICE_DOMAIN.format(uid=os.getuid())
    label = _service_label(mode)
    loaded = _service_loaded(label)
    if previous_version == lock.version:
        if loaded:
            _run(
                (
                    str(release / _RUNNER_BINARY),
                    _STATUS_COMMAND,
                    _READY_OPTION,
                    _STATUS_OUTPUT_OPTION,
                    _JSON_FORMAT,
                    _ENDPOINT_OPTION,
                    _ENDPOINT_PREFIX + str(state / _MODE_SOCKETS[mode]),
                ),
                name=_STATUS_CALL,
                capture=True,
            )
            return
        _launch_generation(release, domain, label, canonical, state, mode)
        return
    if loaded and previous_version is None:
        raise RuntimeError(_SERVICE_CONFLICT)
    if loaded and previous_version is not None:
        previous_binary = root / _RELEASES_NAME / previous_version / _RUNNER_BINARY
        _run(
            (
                str(previous_binary),
                _STATUS_COMMAND,
                _READY_OPTION,
                _STATUS_OUTPUT_OPTION,
                _JSON_FORMAT,
                _ENDPOINT_OPTION,
                _ENDPOINT_PREFIX + str(state / _MODE_SOCKETS[mode]),
            ),
            name=_STATUS_CALL,
            capture=True,
        )
        _run((_LAUNCHCTL, _LAUNCHCTL_BOOTOUT, label), name=_STOP_CALL)
    try:
        _replace_canonical(plist, canonical)
        _launch_generation(release, domain, label, canonical, state, mode)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        try:
            _restore_generation(root, previous_version, previous_plist, canonical, domain, label, state, mode)
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_error:
            raise RuntimeError(_SERVICE_ROLLBACK_FAILED) from rollback_error
        raise RuntimeError(_SERVICE_UPDATE_FAILED) from exc


def stop(mode: ControllerMode = ControllerMode.AUTHORITY) -> None:
    """Unload only the named release Fleet rollout LaunchAgent."""
    lock = _read_lock()
    _host_root()
    release, _, plist = _installed(lock, mode)
    canonical = Path.home() / _LIBRARY / _LAUNCH_AGENTS / _MODE_CANONICAL_PLISTS[mode]
    if canonical.is_symlink() or not canonical.is_file():
        raise RuntimeError(_SERVICE_MISSING)
    if not plist.is_file() or canonical.read_bytes() != plist.read_bytes():
        raise RuntimeError(_SERVICE_CONFLICT)
    uid = os.getuid()
    label = _SERVICE_LABEL.format(domain=_SERVICE_DOMAIN.format(uid=uid), label=_MODE_LABELS[mode])
    _run((_LAUNCHCTL, _LAUNCHCTL_BOOTOUT, label), name=_STOP_CALL)
    if release.is_dir():
        print(_STATUS_MESSAGE.format(mode=mode.value), flush=True)


def status(mode: ControllerMode = ControllerMode.AUTHORITY) -> None:
    """Print the vendor's read-only Fleet readiness and inventory report."""
    lock = _read_lock()
    release, state, _ = _installed(lock, mode)
    endpoint = state / _MODE_SOCKETS[mode]
    report = _run(
        (
            str(release / _RUNNER_BINARY),
            _STATUS_COMMAND,
            _READY_OPTION,
            _STATUS_OUTPUT_OPTION,
            _JSON_FORMAT,
            _ENDPOINT_OPTION,
            _ENDPOINT_PREFIX + str(endpoint),
        ),
        name=_STATUS_CALL,
        capture=True,
    )
    print(report, end=_EMPTY if report.endswith(_NEWLINE) else _NEWLINE)


def _run_install(_: RunnerOperationRequest) -> None:
    install()


def _run_start(request: RunnerOperationRequest) -> None:
    start(request.mode, request.canary_scope, request.canary_profile)


def _run_stop(request: RunnerOperationRequest) -> None:
    stop(request.mode)


def _run_status(request: RunnerOperationRequest) -> None:
    status(request.mode)


_OPERATIONS: dict[Operation, Callable[[RunnerOperationRequest], None]] = {
    Operation.INSTALL: _run_install,
    Operation.START: _run_start,
    Operation.STOP: _run_stop,
    Operation.STATUS: _run_status,
}


def main(argv: list[str] | None = None) -> int:
    configure_logging(_LOG_APPLICATION_NAME)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_ACTION_ARGUMENT, choices=_ACTION_CHOICES)
    parser.add_argument(
        _OPTION_PREFIX + _MODE_ARGUMENT,
        choices=tuple(mode.value for mode in ControllerMode),
        default=_AUTHORITY_MODE,
    )
    parser.add_argument(_CANARY_SCOPE_OPTION)
    parser.add_argument(_CANARY_PROFILE_OPTION)
    arguments = parser.parse_args(argv)
    mode = ControllerMode(arguments.mode)
    operation = Operation(arguments.operation)
    try:
        if mode is not ControllerMode.CANARY and (
            arguments.canary_scope is not None or arguments.canary_profile is not None
        ):
            raise ValueError(_NO_CANARY_SELECTORS)
        request = RunnerOperationRequest(mode, arguments.canary_scope, arguments.canary_profile)
        _OPERATIONS[operation](request)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        logger.error(
            _OPERATION_FAILED_EVENT,
            operation=operation,
            error_kind=type(exc).__name__,
            reason=str(exc),
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
