"""Own a provider-visible bootstrap independently of private hosted job ancestry."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
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
    inspector_access_helper,
    inspector_python,
    make_read_only_tree,
    principal_layout_paths,
    remove_controller_root,
    remove_principal_tree,
    run_isolated_process,
    settle_inspector_principal,
)

SHARED_TEMPORARY_PARENT = Path("/tmp")
BOOTSTRAP_RECEIPT_FILENAME = "release-inspector-bootstrap.json"
_PREFIX = "teleclaude-inspection-"
_CONTROLLER = "controller"
_EVIDENCE = "evidence"
_TOOLCHAIN = "toolchain"
_BIN = "bin"
_NODE = "node"
_NPM = "npm"
_CLAIM = "ownership.json"
_PRIVATE = "inspector-controller-staging"
_CODEX_CONFIG = "codex-home"
_CLAUDE_CONFIG = "claude-config"
_PREFLIGHT_CONFIG = "preflight-config"
_EXECUTABLES = {InspectorRole.CODEX: "codex", InspectorRole.CLAUDE: "claude"}
_PACKAGES = {InspectorRole.CODEX: "@openai/codex@", InspectorRole.CLAUDE: "@anthropic-ai/claude-code@"}
_PACKAGE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_NODE_VERSION = re.compile(rb"v([0-9]+)\.[0-9]+\.[0-9]+\s*")
_VERSION = "--version"
_UTF8 = "utf-8"
_SYSTEM_PATH = ":/usr/local/bin:/usr/bin:/bin"
_HOME = "HOME"
_PATH = "PATH"
_TMPDIR = "TMPDIR"
_LANG = "LANG"
_LC_ALL = "LC_ALL"
_LANGUAGE = "C.UTF-8"
_CONFIG_ENV = {InspectorRole.CODEX: "CODEX_HOME", InspectorRole.CLAUDE: "CLAUDE_CONFIG_DIR"}
_INVALID = "The owned inspector bootstrap is unavailable or unsafe."
_INSTALL_FAILED = "The pinned inspector runtime installation failed."
_VERSION_FAILED = "The isolated inspector runtime did not match its declared version."
_INSTALL_FLAGS = ("install", "--global", "--no-audit", "--no-fund", "--prefix")
_NPM_USER_CONFIG = "--userconfig"
_NPM_GLOBAL_CONFIG = "--globalconfig"
_NPM_CACHE = "--cache"
_NPM_USER_FILENAME = "npm-user-config"
_NPM_GLOBAL_FILENAME = "npm-global-config"
_EMPTY_BYTES = b""
_TIMEOUT = 300
_VERSION_TIMEOUT = 30
_PRIVATE_MODE = 0o700
_SHARED_MODE = 0o711
_FILE_MODE = 0o600
_READ_ONLY_DIRECTORY = 0o555
_READ_ONLY_FILE = 0o444
_READ_ONLY_EXECUTABLE = 0o555
_PATHS = "paths"
_TREES = "trees"
_PATH_KEY = "path"
_MODE_KEY = "mode"
_ACCESS = os.R_OK | os.X_OK
_PRIVATE_ACCESS = os.R_OK | os.W_OK | os.X_OK
_EXCLUSIVE_WRITE = "x"
_REPLACE_WRITE = "w"
_GLOB = "*"
_READY_KEY = "ready"
_CLAIM_BOUND = 4096
_RECEIPT_BOUND = 16384


class InspectorBootstrap(BaseModel):
    """Secret-free ownership and pin receipt; all namespace children have fixed addresses."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    namespace: Path
    evidence_source: Path
    owner_uid: int
    device: int
    inode: int
    claim: str
    versions: dict[InspectorRole, str]
    node_major: int
    ready: bool = False

    @property
    def controller(self) -> Path:
        """Return the controller-owned provider boundary."""
        return self.namespace / _CONTROLLER

    @property
    def evidence(self) -> Path:
        """Return immutable evidence outside the private controller boundary."""
        return self.namespace / _EVIDENCE

    @property
    def toolchain(self) -> Path:
        """Return the read-only owned runtime installation."""
        return self.namespace / _TOOLCHAIN

    @property
    def runtime_path(self) -> str:
        """Select the copied Node before public system utilities."""
        return str(self.toolchain / _BIN) + _SYSTEM_PATH

    def executable(self, role: InspectorRole) -> Path:
        """Resolve the fixed provider entrypoint inside the owned installation."""
        return self.toolchain / _BIN / _EXECUTABLES[role]

    def config(self, role: InspectorRole) -> Path:
        """Return one provider's private persistent configuration directory."""
        _, _, state = principal_layout_paths(role, self.controller)
        return state / (_CODEX_CONFIG if role is InspectorRole.CODEX else _CLAUDE_CONFIG)


def _private_file(path: Path, maximum: int) -> bytes:
    """Read bounded controller-only metadata without following a link."""
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != _FILE_MODE
        or metadata.st_size > maximum
    ):
        raise ValueError(_INVALID)
    return path.read_bytes()


def _validate_ownership(bootstrap: InspectorBootstrap) -> None:
    """Bind deletion and execution authority to the original fresh directory and private claim."""
    namespace = bootstrap.namespace
    parent = SHARED_TEMPORARY_PARENT
    if (
        parent.is_symlink()
        or namespace.parent != parent
        or namespace.is_symlink()
        or not namespace.name.startswith(_PREFIX)
        or namespace.resolve() != namespace
        or bootstrap.owner_uid != os.getuid()
    ):
        raise ValueError(_INVALID)
    metadata = namespace.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != bootstrap.owner_uid
        or metadata.st_dev != bootstrap.device
        or metadata.st_ino != bootstrap.inode
        or stat.S_IMODE(metadata.st_mode) != _SHARED_MODE
    ):
        raise ValueError(_INVALID)
    controller_metadata = bootstrap.controller.lstat()
    if (
        not stat.S_ISDIR(controller_metadata.st_mode)
        or controller_metadata.st_uid != bootstrap.owner_uid
        or stat.S_IMODE(controller_metadata.st_mode) != _SHARED_MODE
    ):
        raise ValueError(_INVALID)
    claim = bootstrap.controller / _PRIVATE / _CLAIM
    private_metadata = claim.parent.lstat()
    if (
        not stat.S_ISDIR(private_metadata.st_mode)
        or private_metadata.st_uid != bootstrap.owner_uid
        or stat.S_IMODE(private_metadata.st_mode) != _PRIVATE_MODE
        or bootstrap.controller.is_symlink()
    ):
        raise ValueError(_INVALID)
    if _private_file(claim, _CLAIM_BOUND).decode(_UTF8) != bootstrap.claim:
        raise ValueError(_INVALID)


def load_bootstrap(receipt: Path, *, require_ready: bool = True) -> InspectorBootstrap:
    """Load only this job's private locator, never an environment-selected provider namespace."""
    bootstrap = InspectorBootstrap.model_validate_json(_private_file(receipt, _RECEIPT_BOUND))
    _validate_ownership(bootstrap)
    if require_ready and not bootstrap.ready:
        raise ValueError(_INVALID)
    return bootstrap


def _write_receipt(receipt: Path, bootstrap: InspectorBootstrap, *, create: bool) -> None:
    """Persist ownership before installation, and publish readiness only after all UID checks."""
    if not create:
        _private_file(receipt, _RECEIPT_BOUND)
    with receipt.open(_EXCLUSIVE_WRITE if create else _REPLACE_WRITE, encoding=_UTF8) as output:
        receipt.chmod(_FILE_MODE)
        output.write(bootstrap.model_dump_json())


def _copy_evidence(source: Path, destination: Path) -> None:
    """Copy immutable input bytes without exposing the original private job directory."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError(_INVALID)
    for path in source.rglob(_GLOB):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError(_INVALID)
    shutil.copytree(source, destination)
    make_read_only_tree(destination)


def _freeze_runtime(root: Path) -> None:
    """Keep controller-owned code readable/executable while refusing escaping package links."""
    for path in root.rglob(_GLOB):
        metadata = path.lstat()
        if metadata.st_uid != os.getuid():
            raise ValueError(_INVALID)
        if path.is_symlink():
            if not path.resolve(strict=True).is_relative_to(root):
                raise ValueError(_INVALID)
            continue
        if not (path.is_dir() or path.is_file()):
            raise ValueError(_INVALID)
        path.chmod(
            _READ_ONLY_DIRECTORY
            if path.is_dir()
            else (_READ_ONLY_EXECUTABLE if metadata.st_mode & 0o111 else _READ_ONLY_FILE)
        )
    root.chmod(_READ_ONLY_DIRECTORY)


def _install_runtime(bootstrap: InspectorBootstrap) -> None:
    """Install the unchanged pinned packages and copied Node into this job's owned prefix."""
    node = shutil.which(_NODE)
    npm = shutil.which(_NPM)
    if node is None or npm is None:
        raise FileNotFoundError(_INSTALL_FAILED)
    binary_directory = bootstrap.toolchain / _BIN
    binary_directory.mkdir(parents=True, mode=_PRIVATE_MODE)
    shutil.copyfile(Path(node).resolve(strict=True), binary_directory / _NODE)
    (binary_directory / _NODE).chmod(_READ_ONLY_EXECUTABLE)
    private = bootstrap.controller / _PRIVATE
    cache = private / _NPM
    user_config = private / _NPM_USER_FILENAME
    global_config = private / _NPM_GLOBAL_FILENAME
    for configuration in (user_config, global_config):
        configuration.write_bytes(_EMPTY_BYTES)
        configuration.chmod(_FILE_MODE)
    # Package installation requires npm's native installer; its stdout/stderr are not public diagnostics.
    result = subprocess.run(
        [
            npm,
            *_INSTALL_FLAGS,
            str(bootstrap.toolchain),
            _NPM_USER_CONFIG,
            str(user_config),
            _NPM_GLOBAL_CONFIG,
            str(global_config),
            _NPM_CACHE,
            str(cache),
            *(_PACKAGES[role] + bootstrap.versions[role] for role in InspectorRole),
        ],
        cwd=cache.parent,
        capture_output=True,
        check=False,
        timeout=_TIMEOUT,
    )
    if result.returncode != 0:
        raise InspectorSetupError(exception_type=RuntimeError.__name__, native_status=result.returncode)
    _freeze_runtime(bootstrap.toolchain)


def verify_provider_paths(bootstrap: InspectorBootstrap, role: InspectorRole) -> None:
    """Verify all runtime/evidence/config paths with the actual isolated UID and launcher."""
    _validate_ownership(bootstrap)
    home, temporary, state = principal_layout_paths(role, bootstrap.controller)
    helper = inspector_access_helper(bootstrap.controller)
    python = inspector_python()
    config = bootstrap.config(role)
    paths = [
        (home, _PRIVATE_ACCESS),
        (temporary, _PRIVATE_ACCESS),
        (state, _PRIVATE_ACCESS),
        (config, _PRIVATE_ACCESS),
        (helper, os.R_OK),
        (python, _ACCESS),
        (bootstrap.executable(role), _ACCESS),
        (bootstrap.toolchain / _BIN / _NODE, _ACCESS),
    ]
    payload = json.dumps(
        {
            _PATHS: [{_PATH_KEY: str(path), _MODE_KEY: mode} for path, mode in paths],
            _TREES: [str(bootstrap.evidence), str(bootstrap.toolchain)],
        }
    ).encode(_UTF8)
    environment = {
        _HOME: str(home),
        _PATH: bootstrap.runtime_path,
        _TMPDIR: str(temporary),
        _LANG: _LANGUAGE,
        _LC_ALL: _LANGUAGE,
    }
    result = run_isolated_process(
        role,
        python,
        (str(helper),),
        bootstrap.evidence,
        environment,
        controller_directory=bootstrap.controller,
        stdin=payload,
    )
    if result.return_code != 0:
        raise InspectorSetupError(exception_type=PermissionError.__name__, native_status=result.return_code)
    if role is InspectorRole.CODEX:
        validate_codex_configuration(bootstrap.evidence, bootstrap.controller, home, temporary, config)
    else:
        validate_claude_configuration(bootstrap.evidence, bootstrap.controller, home, temporary, config)


def _verify_versions(bootstrap: InspectorBootstrap, role: InspectorRole) -> None:
    """Run credential-free native startup with an empty private config as the actual UID."""
    home, temporary, state = principal_layout_paths(role, bootstrap.controller)
    environment = {
        _HOME: str(home),
        _PATH: bootstrap.runtime_path,
        _TMPDIR: str(temporary),
        _LANG: _LANGUAGE,
        _LC_ALL: _LANGUAGE,
        _CONFIG_ENV[role]: str(state / _PREFLIGHT_CONFIG),
    }
    for executable in (bootstrap.toolchain / _BIN / _NODE, bootstrap.executable(role)):
        result = run_isolated_process(
            role,
            executable,
            (_VERSION,),
            bootstrap.evidence,
            environment,
            controller_directory=bootstrap.controller,
            timeout_seconds=_VERSION_TIMEOUT,
        )
        if executable.name == _NODE:
            match = _NODE_VERSION.fullmatch(result.stdout)
            valid = match is not None and int(match.group(1)) == bootstrap.node_major
        else:
            # Both pinned CLIs include their exact package version in their version-only output.
            valid = bootstrap.versions[role].encode(_UTF8) in result.stdout.split()
        if result.return_code != 0 or not valid:
            raise InspectorSetupError(exception_type=ValueError.__name__, native_status=result.return_code)


def create_bootstrap(
    source: Path, receipt: Path, versions: dict[InspectorRole, str], node_major: int
) -> InspectorBootstrap:
    """Allocate one exclusive shared namespace; preflight every path before auth use is possible."""
    if set(versions) != set(InspectorRole) or any(not _PACKAGE_VERSION.fullmatch(v) for v in versions.values()):
        raise ValueError(_VERSION_FAILED)
    if node_major < 1 or SHARED_TEMPORARY_PARENT.is_symlink() or not SHARED_TEMPORARY_PARENT.is_dir():
        raise ValueError(_INVALID)
    if receipt.exists() or receipt.is_symlink():
        raise ValueError(_INVALID)
    namespace = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=SHARED_TEMPORARY_PARENT))
    metadata = namespace.stat()
    bootstrap = InspectorBootstrap(
        namespace=namespace,
        evidence_source=source.resolve(),
        owner_uid=os.getuid(),
        device=metadata.st_dev,
        inode=metadata.st_ino,
        claim=uuid.uuid4().hex,
        versions=versions,
        node_major=node_major,
    )
    try:
        create_controller_root(bootstrap.controller, temporary_parent=namespace)
        private = bootstrap.controller / _PRIVATE
        private.mkdir(mode=_PRIVATE_MODE)
        claim = private / _CLAIM
        claim.write_text(bootstrap.claim, encoding=_UTF8)
        claim.chmod(_FILE_MODE)
        namespace.chmod(_SHARED_MODE)
        _write_receipt(receipt, bootstrap, create=True)
        _copy_evidence(source, bootstrap.evidence)
        _install_runtime(bootstrap)
        for role in InspectorRole:
            home, temporary, state = create_principal_layout(role, bootstrap.controller)
            config = create_principal_directory(role, bootstrap.controller, bootstrap.config(role))
            create_principal_directory(role, bootstrap.controller, state / _PREFLIGHT_CONFIG)
            if role is InspectorRole.CODEX:
                prepare_codex_configuration(bootstrap.evidence, bootstrap.controller, home, temporary, config)
            else:
                prepare_claude_configuration(bootstrap.evidence, bootstrap.controller, home, temporary, config)
            verify_provider_paths(bootstrap, role)
            _verify_versions(bootstrap, role)
        bootstrap = bootstrap.model_copy(update={_READY_KEY: True})
        _write_receipt(receipt, bootstrap, create=False)
        return bootstrap
    except BaseException:
        # An already-persisted ownership receipt leaves the always-run cleanup its exact namespace.
        if not receipt.exists():
            if bootstrap.controller.exists():
                remove_controller_root(bootstrap.controller, temporary_parent=namespace)
            namespace.rmdir()
        raise


def cleanup_bootstrap(receipt: Path) -> None:
    """Remove only the claimed namespace after both dedicated UIDs have settled."""
    if not receipt.exists() and not receipt.is_symlink():
        return
    bootstrap = load_bootstrap(receipt, require_ready=False)
    for role in InspectorRole:
        settle_inspector_principal(role)
    for role in InspectorRole:
        target = bootstrap.controller / role.value
        if target.exists() or target.is_symlink():
            remove_principal_tree(role, bootstrap.controller, target)
    remove_controller_root(bootstrap.controller, temporary_parent=bootstrap.namespace)
    for root in (bootstrap.evidence, bootstrap.toolchain):
        if not root.exists():
            continue
        if root.is_symlink():
            raise ValueError(_INVALID)
        for path in root.rglob(_GLOB):
            if not path.is_symlink() and path.is_dir():
                if path.stat().st_uid != bootstrap.owner_uid:
                    raise ValueError(_INVALID)
                path.chmod(_PRIVATE_MODE)
        root.chmod(_PRIVATE_MODE)
        shutil.rmtree(root)
    bootstrap.namespace.rmdir()
    receipt.unlink()
