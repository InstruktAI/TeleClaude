"""Prepare one pinned native provider in its own fresh hosted job."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from tools.release.claude_inspector import prepare_claude_configuration, validate_claude_configuration
from tools.release.codex_inspector import prepare_codex_configuration, validate_codex_configuration
from tools.release.isolated_inspection import (
    InspectorRole,
    InspectorSetupError,
    create_controller_root,
    create_principal_directory,
    create_principal_layout,
    make_read_only_tree,
    principal_layout_paths,
    remove_controller_root,
    run_isolated_process,
    settle_inspector_principal,
)

BOOTSTRAP_RECEIPT_FILENAME = "release-inspector-bootstrap.json"
_CONTROLLER = "release-inspector"
_CODEX_CONFIG = "codex-home"
_CLAUDE_CONFIG = "claude-config"
_EXECUTABLES = {InspectorRole.CODEX: "codex", InspectorRole.CLAUDE: "claude"}
_PACKAGES = {InspectorRole.CODEX: "@openai/codex@", InspectorRole.CLAUDE: "@anthropic-ai/claude-code@"}
_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_NODE_VERSION_PATTERN = re.compile(rb"v([0-9]+)\.[0-9]+\.[0-9]+\s*")
_VERSION_FLAG = "--version"
_NODE = "node"
_NPM = "npm"
_INSTALL = ("install", "--global", "--no-audit", "--no-fund")
_PRIVATE_MODE = 0o700
_FILE_MODE = 0o600
_UTF8 = "utf-8"
_HOME = "HOME"
_PATH = "PATH"
_TMPDIR = "TMPDIR"
_LANG = "LANG"
_LC_ALL = "LC_ALL"
_LANGUAGE = "C.UTF-8"
_CONFIG_ENV = {InspectorRole.CODEX: "CODEX_HOME", InspectorRole.CLAUDE: "CLAUDE_CONFIG_DIR"}
_INVALID = "The job-local native inspector setup is unavailable or unsafe."
_TIMEOUT = 300
_READY = "ready"
_EXECUTABLE_PATH_KEY = "executable_path"
_RUNTIME_PATH_KEY = "runtime_path"
_READ_MODE = "rb"
_WRITE_MODE = "x"
_REPLACE_MODE = "w"
_VERSION_TIMEOUT = 30
_RECEIPT_BOUND = 16384
_LINUX = "Linux"
_PACKAGE_MANIFEST = "package.json"
_CODEX_PACKAGE_NAME = "@openai/codex"
_CODEX_WRAPPER = Path("bin/codex.js")
_CODEX_NATIVE_LAYOUTS = {
    "x86_64": ("codex-linux-x64", "x86_64-unknown-linux-musl", "-linux-x64"),
    "aarch64": ("codex-linux-arm64", "aarch64-unknown-linux-musl", "-linux-arm64"),
}
_NODE_MODULES = "node_modules"
_OPENAI_SCOPE = "@openai"
_VENDOR = "vendor"
_NATIVE_BINARY = Path("bin/codex")
_WRAPPER_PARENT_INDEX = 6


class NpmPackageIdentity(BaseModel):
    """The public pinned package identity, without interpreting unrelated npm fields."""

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)
    name: str
    version: str


def _codex_native_executable(wrapper: Path, version: str) -> Path:
    """Resolve only the pinned npm wrapper's installed Linux platform package."""
    layout = _CODEX_NATIVE_LAYOUTS.get(platform.machine())
    if platform.system() != _LINUX or layout is None:
        raise ValueError(_INVALID)
    package_root = wrapper.resolve().parent.parent
    if wrapper.resolve() != package_root / _CODEX_WRAPPER:
        raise ValueError(_INVALID)
    package, target, suffix = layout
    native_root = package_root / _NODE_MODULES / _OPENAI_SCOPE / package
    for root, expected in ((package_root, version), (native_root, version + suffix)):
        manifest = root / _PACKAGE_MANIFEST
        if manifest.resolve() != manifest:
            raise ValueError(_INVALID)
        identity = NpmPackageIdentity.model_validate_json(manifest.read_bytes())
        if identity.name != _CODEX_PACKAGE_NAME or identity.version != expected:
            raise ValueError(_INVALID)
    native = native_root / _VENDOR / target / _NATIVE_BINARY
    if native.resolve() != native or not native.is_file() or not os.access(native, os.X_OK):
        raise ValueError(_INVALID)
    return native


class InspectorBootstrap(BaseModel):
    """Private job-local addresses and pins, never transported between jobs."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    controller: Path
    evidence: Path
    role: InspectorRole
    version: str
    executable_path: Path
    runtime_path: str
    ready: bool = False

    @property
    def evidence_source(self) -> Path:
        """Keep the captured evidence identity without a second materialization."""
        return self.evidence

    def executable(self, role: InspectorRole) -> Path:
        """Refuse another provider's executable in this job."""
        if role is not self.role:
            raise ValueError(_INVALID)
        return self.executable_path

    def config(self, role: InspectorRole) -> Path:
        """Select only this job's private provider configuration."""
        self.executable(role)
        _, _, state = principal_layout_paths(role, self.controller)
        return state / (_CODEX_CONFIG if role is InspectorRole.CODEX else _CLAUDE_CONFIG)


def load_bootstrap(receipt: Path, *, require_ready: bool = True) -> InspectorBootstrap:
    """Read bounded private setup and bind deletion to this exact job-local parent."""
    descriptor = os.open(receipt, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, _READ_MODE) as source:
        metadata = os.fstat(source.fileno())
        if (
            metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o777 != _FILE_MODE
            or metadata.st_size > _RECEIPT_BOUND
        ):
            raise ValueError(_INVALID)
        bootstrap = InspectorBootstrap.model_validate_json(source.read(_RECEIPT_BOUND + 1))
    if bootstrap.controller != receipt.parent.resolve() / _CONTROLLER or bootstrap.controller.is_symlink():
        raise ValueError(_INVALID)
    root = bootstrap.controller.stat()
    if root.st_uid != os.getuid() or root.st_mode & 0o777 != _PRIVATE_MODE or (require_ready and not bootstrap.ready):
        raise ValueError(_INVALID)
    return bootstrap


def _write_receipt(receipt: Path, bootstrap: InspectorBootstrap, *, create: bool) -> None:
    """Keep addresses private and local to the provider job."""
    with receipt.open(_WRITE_MODE if create else _REPLACE_MODE, encoding=_UTF8) as output:
        os.fchmod(output.fileno(), _FILE_MODE)
        output.write(bootstrap.model_dump_json())


def verify_provider_paths(bootstrap: InspectorBootstrap, role: InspectorRole) -> None:
    """Check native installation, evidence and exact private configuration before auth use."""
    executable = bootstrap.executable(role)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(_INVALID)
    home, temporary, _ = principal_layout_paths(role, bootstrap.controller)
    if bootstrap.evidence.is_symlink() or not bootstrap.evidence.is_dir():
        raise ValueError(_INVALID)
    if role is InspectorRole.CODEX:
        if len(executable.parents) <= _WRAPPER_PARENT_INDEX:
            raise ValueError(_INVALID)
        wrapper = executable.parents[_WRAPPER_PARENT_INDEX] / _CODEX_WRAPPER
        if _codex_native_executable(wrapper, bootstrap.version) != executable:
            raise ValueError(_INVALID)
        validate_codex_configuration(
            bootstrap.evidence,
            bootstrap.controller,
            home,
            temporary,
            bootstrap.config(role),
            native_executable=executable,
        )
    else:
        validate_claude_configuration(bootstrap.evidence, bootstrap.controller, home, temporary, bootstrap.config(role))


def create_bootstrap(
    source: Path, receipt: Path, versions: dict[InspectorRole, str], node_major: int
) -> InspectorBootstrap:
    """Install only this fresh job's provider, preserving ordinary private runner ancestry."""
    if len(versions) != 1 or receipt.exists() or receipt.is_symlink():
        raise ValueError(_INVALID)
    role, version = next(iter(versions.items()))
    if not _VERSION_PATTERN.fullmatch(version) or node_major < 1:
        raise ValueError(_INVALID)
    controller = receipt.parent.resolve() / _CONTROLLER
    create_controller_root(controller, temporary_parent=receipt.parent)
    bootstrap = InspectorBootstrap(
        controller=controller,
        evidence=source.resolve(),
        role=role,
        version=version,
        executable_path=Path(_EXECUTABLES[role]),
        runtime_path=os.defpath,
    )
    _write_receipt(receipt, bootstrap, create=True)
    home, temporary, state = create_principal_layout(role, controller)
    config = create_principal_directory(
        role, controller, state / (_CODEX_CONFIG if role is InspectorRole.CODEX else _CLAUDE_CONFIG)
    )
    npm = shutil.which(_NPM)
    node = shutil.which(_NODE)
    if npm is None or node is None:
        raise ValueError(_INVALID)
    installation = subprocess.run(
        [npm, *_INSTALL, _PACKAGES[role] + version], capture_output=True, timeout=_TIMEOUT, check=False
    )
    if installation.returncode:
        raise InspectorSetupError(exception_type=RuntimeError.__name__, native_status=installation.returncode)
    executable = shutil.which(_EXECUTABLES[role])
    if executable is None:
        raise ValueError(_INVALID)
    native_executable = (
        _codex_native_executable(Path(executable), version) if role is InspectorRole.CODEX else Path(executable)
    )
    bootstrap = bootstrap.model_copy(
        update={
            _EXECUTABLE_PATH_KEY: native_executable,
            _RUNTIME_PATH_KEY: str(Path(node).parent)
            + os.pathsep
            + os.defpath
            + os.pathsep
            + str(Path(executable).parent),
        }
    )
    make_read_only_tree(bootstrap.evidence)
    if role is InspectorRole.CODEX:
        prepare_codex_configuration(
            bootstrap.evidence, controller, home, temporary, config, native_executable=native_executable
        )
    else:
        prepare_claude_configuration(bootstrap.evidence, controller, home, temporary, config)
    verify_provider_paths(bootstrap, role)
    environment = {
        _HOME: str(home),
        _PATH: bootstrap.runtime_path,
        _TMPDIR: str(temporary),
        _LANG: _LANGUAGE,
        _LC_ALL: _LANGUAGE,
        _CONFIG_ENV[role]: str(config),
    }
    node_result = run_isolated_process(
        role,
        Path(node),
        (_VERSION_FLAG,),
        bootstrap.evidence,
        environment,
        controller_directory=controller,
        timeout_seconds=_VERSION_TIMEOUT,
    )
    match = _NODE_VERSION_PATTERN.fullmatch(node_result.stdout)
    if node_result.return_code or match is None or int(match.group(1)) != node_major:
        raise InspectorSetupError(exception_type=ValueError.__name__, native_status=node_result.return_code)
    result = run_isolated_process(
        role,
        native_executable,
        (_VERSION_FLAG,),
        bootstrap.evidence,
        environment,
        controller_directory=controller,
        timeout_seconds=_VERSION_TIMEOUT,
    )
    if result.return_code or version.encode(_UTF8) not in result.stdout.split():
        raise InspectorSetupError(exception_type=ValueError.__name__, native_status=result.return_code)
    bootstrap = bootstrap.model_copy(update={_READY: True})
    _write_receipt(receipt, bootstrap, create=False)
    return bootstrap


def cleanup_bootstrap(receipt: Path) -> None:
    """Remove only this job's owned state after its native descendants settle."""
    if not receipt.exists() and not receipt.is_symlink():
        return
    bootstrap = load_bootstrap(receipt, require_ready=False)
    settle_inspector_principal(bootstrap.role)
    remove_controller_root(bootstrap.controller, temporary_parent=receipt.parent)
    receipt.unlink()
