"""Infrastructure effects for signing locally built macOS launchers."""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.agent_registry import AgentName
from teleclaude.paths import LAUNCHER_SIGNING_DIR
from teleclaude.runtime.binaries import TMUX_LAUNCHER_CANDIDATES, TMUX_LAUNCHER_OVERRIDE_KEYS

_SECURITY = "/usr/bin/security"
_SECURITY_INTERACTIVE_FLAG = "-i"
_CODESIGN = "/usr/bin/codesign"
_OPENSSL = "/usr/bin/openssl"
_SWIFTC = "/usr/bin/swiftc"
_XCRUN = "/usr/bin/xcrun"
_XCRUN_FIND_FLAG = "--find"
_SWIFTC_NAME = "swiftc"
_KEYCHAIN_SUFFIX = ".keychain-db"
_KEYCHAIN_FILE_NAME = "launcher-signing" + _KEYCHAIN_SUFFIX
_SECRET_FILE_NAME = "unlock-secret"
_SOURCE_FILE_NAME = "main.swift"
_CONTENTS_DIRECTORY = "Contents"
_INFO_PLIST = "Info.plist"
_EXECUTABLE_DIRECTORY = "MacOS"
_PROBE_DIRECTORY_PREFIX = "teleclaude-launcher-signing-"
_PRIVATE_KEY_FILE_NAME = "authority-key.pem"
_CERTIFICATE_FILE_NAME = "authority-cert.pem"
_AUTHORITY_BUNDLE_FILE_NAME = "authority.p12"
_IMPORT_PASSWORD_FILE_NAME = "import-password"
_NAME = "InstruktAI TeleClaude Launcher"
_KEYCHAIN_LOCK_SECONDS = "300"
_CERTIFICATE_LIFETIME_DAYS = "3650"
_KEY_BITS = "2048"
_KEY_LENGTH = 2048
_COMMAND_TIMEOUT_SECONDS = 45
_CERTIFICATE_LABEL = _NAME
_SIGNING_PARTITIONS = "apple-tool:,apple:,codesign:"
_SIGNING_TOOL = _CODESIGN
_SECURITY_TOOL = _SECURITY
_DEFAULT_VERSION = "1.0"
_TMUX_VERSION = "1.2"
_BUNDLE_PREFIX = "ai.instrukt."
_BUNDLE_SUFFIX = "launcher"
_SWIFT_OPTIMIZATION = "-O"
_NPM_PREFIX_ACTION = "prefix"
_NPM_GLOBAL_FLAG = "-g"
_TMUX_EXECUTABLE = "tmux"
_CLAUDE_EXECUTABLE = "claude"
_CODEX_EXECUTABLE = "codex"
_GEMINI_EXECUTABLE = "agy"
_GEMINI_LAUNCHER_EXECUTABLE = "gemini-launcher"
_DEEPSEEK_EXECUTABLE = "dsh"
_TMUX_OVERRIDE_KEYS = ", ".join(f'"{key}"' for key in TMUX_LAUNCHER_OVERRIDE_KEYS)
_CLAUDE_OVERRIDE_KEYS = '"CLAUDE_PATH"'
_CODEX_OVERRIDE_KEYS = '"CODEX_PATH"'
_GEMINI_OVERRIDE_KEYS = '"GEMINI_PATH"'
_DEEPSEEK_OVERRIDE_KEYS = '"DSH_PATH"'
_TMUX_CANDIDATES = ", ".join(f'"{path}"' for path in TMUX_LAUNCHER_CANDIDATES)
_DEEPSEEK_CANDIDATES = '"/opt/homebrew/bin/dsh", "/usr/local/bin/dsh"'
_TMUX_POLICY = ".tmuxServer"
_PASSTHROUGH_POLICY = ".passthrough"
_STRICT_TRUE = "true"
_STRICT_FALSE = "false"
_EXIT_ONE = "1"
_EXIT_127 = "127"
_PLIST_NAME = "CFBundleName"
_PLIST_IDENTIFIER = "CFBundleIdentifier"
_PLIST_VERSION = "CFBundleVersion"
_PLIST_SHORT_VERSION = "CFBundleShortVersionString"
_PLIST_EXECUTABLE = "CFBundleExecutable"
_PLIST_PACKAGE_TYPE = "CFBundlePackageType"
_PLIST_APPLICATION = "APPL"
_PLIST_UI_ELEMENT = "LSUIElement"
_CERTIFICATE_NAME_PATTERN = re.compile(r'([A-F0-9]{40})\s+"([^"]+)"')
_CERTIFICATE_HASH_PATTERN = re.compile(r"SHA-1 hash: ([A-Fa-f0-9]{40})")
_IDENTIFIER_PATTERN = re.compile(r"Identifier=([^\s]+)")
_LEAF_PATTERN = re.compile(r'certificate leaf = H"([A-Fa-f0-9]+)"')
_CDHASH_PATTERN = re.compile(r"CDHash=([A-Fa-f0-9]+)")
_AUTHORIZATION_PATTERN = re.compile(r"^\s*\d+: /usr/bin/codesign \(OK\)$", re.MULTILINE)
_OPENSSL_SUBJECT = "/CN=" + _NAME
_OPENSSL_BASE_CONSTRAINT = "basicConstraints=critical,CA:false"
_OPENSSL_KEY_USAGE = "keyUsage=critical,digitalSignature"
_OPENSSL_EXTENDED_USAGE = "extendedKeyUsage=critical,codeSigning"
_P12_CERTIFICATE_PBE = "PBE-SHA1-3DES"
_P12_KEY_PBE = "PBE-SHA1-3DES"
_P12_MAC_ALGORITHM = "sha1"
_TEXT_ENCODING = "utf-8"
_WRITE_MODE = "w"
_OPENSSL_REQUEST_ACTION = "req"
_OPENSSL_X509_COMMAND = "x509"
_OPENSSL_X509_FLAG = "-x509"
_OPENSSL_NEW_KEY_FLAG = "-newkey"
_OPENSSL_RSA_KEY_TYPE = "rsa:"
_OPENSSL_NO_NODES_FLAG = "-nodes"
_OPENSSL_DAYS_FLAG = "-days"
_OPENSSL_KEY_OUTPUT_FLAG = "-keyout"
_OPENSSL_CERTIFICATE_OUTPUT_FLAG = "-out"
_OPENSSL_SUBJECT_FLAG = "-subj"
_OPENSSL_EXTENSION_FLAG = "-addext"
_OPENSSL_PKCS12_ACTION = "pkcs12"
_OPENSSL_EXPORT_FLAG = "-export"
_OPENSSL_CERTIFICATE_PBE_FLAG = "-certpbe"
_OPENSSL_KEY_PBE_FLAG = "-keypbe"
_OPENSSL_MAC_ALGORITHM_FLAG = "-macalg"
_OPENSSL_KEY_INPUT_FLAG = "-inkey"
_OPENSSL_INPUT_FLAG = "-in"
_OPENSSL_NAME_FLAG = "-name"
_OPENSSL_PASSWORD_OUTPUT_FLAG = "-passout"
_OPENSSL_PASSWORD_FILE_PREFIX = "file:"
_OPENSSL_CHECK_EXPIRY_FLAG = "-checkend"
_OPENSSL_ZERO_SECONDS = "0"
_OPENSSL_NO_OUTPUT_FLAG = "-noout"
_SWIFTC_OUTPUT_FLAG = "-o"
_STDIN_PATH = "/dev/stdin"
_DOUBLE_QUOTE = '"'
_CODE_SIGNING_POLICY = "codesigning"
_LINE_SEPARATOR = "\n"
_EMPTY = ""
_TIMEOUT_FAILURE = "launcher-signing command timed out"
_MISSING_TOOL_FAILURE = "required macOS signing tool is unavailable"
_STORE_FAILURE = "the launcher signing store could not be opened"
_SECRET_FAILURE = "the launcher signing unlock secret is unavailable or rejected"
_AUTHORITY_FAILURE = "the launcher signing authority is missing or ambiguous"
_UNAUTHORIZED_FAILURE = "the launcher signing key is not authorized for unattended use"
_STORE_DISCOVERY_FAILURE = "the user keychain search list could not be read reliably"
_STORE_REGISTRATION_FAILURE = "the dedicated launcher signing store could not be registered"
_ROSTER_GAP_FAILURE = "launcher definitions do not cover canonical agent(s): {agents}"
_SWIFTC_UNAVAILABLE_FAILURE = "Swift compiler is unavailable; xcrun could not resolve swiftc: {detail}"
_SWIFTC_NO_PATH = "no compiler path returned"
_STRICT_SIGNATURE_FAILURE = "{bundle}: strict signature verification failed: {reason}"
_SIGNATURE_DETAILS_FAILURE = "{bundle}: signature details could not be read"
_SIGNATURE_REQUIREMENT_FAILURE = "{bundle}: signing requirement could not be read"
_SIGNATURE_FINGERPRINT_MISSING = "{bundle}: signing certificate fingerprint is missing"
_SIGNATURE_IDENTIFIER_MISMATCH = "{bundle}: identifier {observed} differs from expected {expected}"
_SIGNATURE_HASH_MISSING = "{bundle}: code-directory hash is missing"
_SIGNATURE_FINGERPRINT_MISMATCH = "{bundle}: signing fingerprint {observed} differs from expected {expected}"
_EMPTY_VERIFICATION_REASON = "codesign returned a nonzero status without diagnostics"


class SigningCommandKind(StrEnum):
    """Structured failure kinds for bounded operating-system commands."""

    FAILED = "failed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    COMPILER_UNAVAILABLE = "compiler_unavailable"
    COMPILE_FAILED = "compile_failed"
    ROSTER_GAP = "roster_gap"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class SigningCommandResult:
    """Captured result from one bounded native signing command."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class SigningCommandError(RuntimeError):
    """A native signing command failed or exceeded its deadline."""

    def __init__(self, kind: SigningCommandKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class LauncherId(StrEnum):
    """Canonical launcher build targets."""

    TMUX = "tmux"
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"


@dataclass(frozen=True)
class LauncherDefinition:
    """Build-time configuration for one stable launcher identity."""

    target: LauncherId
    display_name: str
    target_executable: str
    executable: str
    version: str
    override_keys: str
    fixed_candidates: str
    override_strict: str
    strict_exit_code: str
    argv_policy: str

    @property
    def bundle_identifier(self) -> str:
        return _BUNDLE_PREFIX + self.target.value + _BUNDLE_SUFFIX


@dataclass(frozen=True)
class LauncherSignature:
    """Structured signature identity read from a launcher bundle."""

    fingerprint: str
    identifier: str
    code_directory_hash: str


_DEFINITIONS = {
    LauncherId.TMUX: LauncherDefinition(
        LauncherId.TMUX,
        "TmuxLauncher",
        _TMUX_EXECUTABLE,
        "tmux-launcher",
        _TMUX_VERSION,
        _TMUX_OVERRIDE_KEYS,
        _TMUX_CANDIDATES,
        _STRICT_FALSE,
        _EXIT_127,
        _TMUX_POLICY,
    ),
    LauncherId.CLAUDE: LauncherDefinition(
        LauncherId.CLAUDE,
        "ClaudeLauncher",
        _CLAUDE_EXECUTABLE,
        "claude-launcher",
        _DEFAULT_VERSION,
        _CLAUDE_OVERRIDE_KEYS,
        _EMPTY,
        _STRICT_TRUE,
        _EXIT_ONE,
        _PASSTHROUGH_POLICY,
    ),
    LauncherId.CODEX: LauncherDefinition(
        LauncherId.CODEX,
        "CodexLauncher",
        _CODEX_EXECUTABLE,
        "codex-launcher",
        _DEFAULT_VERSION,
        _CODEX_OVERRIDE_KEYS,
        _EMPTY,
        _STRICT_FALSE,
        _EXIT_127,
        _PASSTHROUGH_POLICY,
    ),
    LauncherId.GEMINI: LauncherDefinition(
        LauncherId.GEMINI,
        "GeminiLauncher",
        _GEMINI_EXECUTABLE,
        _GEMINI_LAUNCHER_EXECUTABLE,
        _DEFAULT_VERSION,
        _GEMINI_OVERRIDE_KEYS,
        _EMPTY,
        _STRICT_FALSE,
        _EXIT_127,
        _PASSTHROUGH_POLICY,
    ),
    LauncherId.DEEPSEEK: LauncherDefinition(
        LauncherId.DEEPSEEK,
        "DeepSeekLauncher",
        _DEEPSEEK_EXECUTABLE,
        "deepseek-launcher",
        _DEFAULT_VERSION,
        _DEEPSEEK_OVERRIDE_KEYS,
        _DEEPSEEK_CANDIDATES,
        _STRICT_FALSE,
        _EXIT_127,
        _PASSTHROUGH_POLICY,
    ),
}


def launcher_signing_directory() -> Path:
    """Return the private directory for the machine-local signing authority."""
    return LAUNCHER_SIGNING_DIR


def launcher_keychain_path(directory: Path | None = None) -> Path:
    """Return the dedicated launcher signing keychain path."""
    return (directory or LAUNCHER_SIGNING_DIR) / _KEYCHAIN_FILE_NAME


def launcher_secret_path(directory: Path | None = None) -> Path:
    """Return the machine-local keychain unlock secret path."""
    return (directory or LAUNCHER_SIGNING_DIR) / _SECRET_FILE_NAME


def _run_command(
    argv: Sequence[str],
    *,
    timeout: int = _COMMAND_TIMEOUT_SECONDS,
    input_text: str | None = None,
) -> SigningCommandResult:
    """Run bounded OS tools with no Python binding here for Keychain, codesign, Swift, or OpenSSL."""
    try:
        result = subprocess.run(
            tuple(argv),
            input=input_text,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise SigningCommandError(SigningCommandKind.TIMEOUT, _TIMEOUT_FAILURE) from error
    except FileNotFoundError as error:
        if argv[0] == _SWIFTC:
            raise SigningCommandError(SigningCommandKind.COMPILER_UNAVAILABLE, _SWIFTC_UNAVAILABLE_FAILURE) from error
        raise SigningCommandError(SigningCommandKind.UNAVAILABLE, _MISSING_TOOL_FAILURE) from error
    return SigningCommandResult(tuple(argv), result.returncode, result.stdout, result.stderr)


def _run_security_script(commands: Sequence[Sequence[str]]) -> SigningCommandResult:
    """Send secret-bearing Security commands on stdin, outside the process arguments."""
    script = _LINE_SEPARATOR.join(shlex.join(command) for command in commands) + _LINE_SEPARATOR
    return _run_command((_SECURITY, _SECURITY_INTERACTIVE_FLAG), input_text=script)


def _require_success(
    result: SigningCommandResult,
    message: str,
    kind: SigningCommandKind = SigningCommandKind.FAILED,
) -> None:
    if result.returncode != 0:
        raise SigningCommandError(kind, message)


def _ensure_swift_compiler() -> None:
    """Resolve the active compiler rather than accepting macOS's always-present shim."""
    # xcrun owns the selected Xcode or Command Line Tools path; Python has no native resolver for it.
    try:
        result = _run_command((_XCRUN, _XCRUN_FIND_FLAG, _SWIFTC_NAME))
    except SigningCommandError as error:
        if error.kind is SigningCommandKind.UNAVAILABLE:
            raise SigningCommandError(
                SigningCommandKind.COMPILER_UNAVAILABLE,
                _SWIFTC_UNAVAILABLE_FAILURE.format(detail=error),
            ) from error
        raise
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or _SWIFTC_NO_PATH
        raise SigningCommandError(
            SigningCommandKind.COMPILER_UNAVAILABLE,
            _SWIFTC_UNAVAILABLE_FAILURE.format(detail=detail),
        )


def ensure_signing_store(*, directory: Path | None = None) -> str:
    """Create and unlock the dedicated signing store without changing keychain search paths."""
    signing_directory = directory or launcher_signing_directory()
    signing_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    signing_directory.chmod(0o700)
    secret_path = launcher_secret_path(signing_directory)
    keychain = launcher_keychain_path(signing_directory)
    if not secret_path.exists() and keychain.is_file():
        raise SigningCommandError(SigningCommandKind.FAILED, _SECRET_FAILURE)
    if not secret_path.exists():
        secret = secrets.token_urlsafe(_KEY_LENGTH // 8)
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, _WRITE_MODE, encoding=_TEXT_ENCODING) as handle:
            handle.write(secret + _LINE_SEPARATOR)
    try:
        secret = secret_path.read_text(encoding=_TEXT_ENCODING).rstrip(_LINE_SEPARATOR)
    except OSError as error:
        raise SigningCommandError(SigningCommandKind.FAILED, _SECRET_FAILURE) from error
    secret_path.chmod(0o600)
    commands: list[Sequence[str]] = []
    if not keychain.is_file():
        commands.append((_SECURITY_CREATE_KEYCHAIN, _SECURITY_PASSWORD_FLAG, secret, str(keychain)))
    commands.append((_SECURITY_UNLOCK_KEYCHAIN, _SECURITY_PASSWORD_FLAG, secret, str(keychain)))
    commands.append((_SECURITY_KEYCHAIN_SETTINGS, _SECURITY_LOCK_FLAG, _KEYCHAIN_LOCK_SECONDS, str(keychain)))
    result = _run_security_script(commands)
    if result.returncode != 0:
        message = _SECRET_FAILURE if keychain.exists() else _STORE_FAILURE
        raise SigningCommandError(SigningCommandKind.FAILED, message)
    return secret


def register_signing_store(*, keychain: Path | None = None) -> None:
    """Append the dedicated store to the user search list only when it is absent."""
    try:
        target = (keychain or launcher_keychain_path()).expanduser().resolve()
        existing = _read_user_keychain_search_list()
        resolved_existing = tuple(Path(entry).expanduser().resolve() for entry in existing)
    except SigningCommandError:
        raise
    except (OSError, RuntimeError, UnicodeError) as error:
        raise SigningCommandError(SigningCommandKind.FAILED, _STORE_DISCOVERY_FAILURE) from error
    if target in resolved_existing:
        return
    intended = (*existing, str(target))
    updated = _run_command(
        (
            _SECURITY,
            _SECURITY_LIST_KEYCHAINS,
            _SECURITY_DOMAIN_OPTION,
            _SECURITY_USER_DOMAIN,
            _SECURITY_SET_LIST_OPTION,
            *intended,
        )
    )
    _require_success(updated, _STORE_REGISTRATION_FAILURE)
    try:
        confirmed = _read_user_keychain_search_list()
        resolved_confirmed = tuple(Path(entry).expanduser().resolve() for entry in confirmed)
        resolved_intended = tuple(Path(entry).expanduser().resolve() for entry in intended)
    except SigningCommandError:
        raise
    except (OSError, RuntimeError, UnicodeError) as error:
        raise SigningCommandError(SigningCommandKind.FAILED, _STORE_DISCOVERY_FAILURE) from error
    if resolved_confirmed != resolved_intended:
        raise SigningCommandError(SigningCommandKind.FAILED, _STORE_REGISTRATION_FAILURE)


def _read_user_keychain_search_list() -> tuple[str, ...]:
    result = _run_command((_SECURITY, _SECURITY_LIST_KEYCHAINS, _SECURITY_DOMAIN_OPTION, _SECURITY_USER_DOMAIN))
    _require_success(result, _STORE_DISCOVERY_FAILURE)
    entries: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = shlex.split(stripped)
        except ValueError as error:
            raise SigningCommandError(SigningCommandKind.FAILED, _STORE_DISCOVERY_FAILURE) from error
        if len(parsed) != 1 or not stripped.startswith(_DOUBLE_QUOTE) or not stripped.endswith(_DOUBLE_QUOTE):
            raise SigningCommandError(SigningCommandKind.FAILED, _STORE_DISCOVERY_FAILURE)
        entries.append(parsed[0])
    if not entries:
        raise SigningCommandError(SigningCommandKind.FAILED, _STORE_DISCOVERY_FAILURE)
    return tuple(entries)


def create_signing_authority(
    secret: str,
    *,
    keychain: Path | None = None,
    temporary_root: Path | None = None,
) -> str:
    """Create a self-signed authority and authorize codesign in the dedicated store."""
    target_keychain = keychain or launcher_keychain_path()
    with tempfile.TemporaryDirectory(prefix=_PROBE_DIRECTORY_PREFIX, dir=temporary_root) as temporary:
        root = Path(temporary)
        private_key = root / _PRIVATE_KEY_FILE_NAME
        certificate = root / _CERTIFICATE_FILE_NAME
        authority_bundle = root / _AUTHORITY_BUNDLE_FILE_NAME
        import_password = root / _IMPORT_PASSWORD_FILE_NAME
        password = secrets.token_urlsafe(_KEY_LENGTH // 8)
        import_password.write_text(password + _LINE_SEPARATOR, encoding=_TEXT_ENCODING)
        import_password.chmod(0o600)
        generated = _run_command(
            (
                _OPENSSL,
                _OPENSSL_REQUEST_ACTION,
                _OPENSSL_X509_FLAG,
                _OPENSSL_NEW_KEY_FLAG,
                _OPENSSL_RSA_KEY_TYPE + _KEY_BITS,
                _OPENSSL_NO_NODES_FLAG,
                _OPENSSL_DAYS_FLAG,
                _CERTIFICATE_LIFETIME_DAYS,
                _OPENSSL_KEY_OUTPUT_FLAG,
                str(private_key),
                _OPENSSL_CERTIFICATE_OUTPUT_FLAG,
                str(certificate),
                _OPENSSL_SUBJECT_FLAG,
                _OPENSSL_SUBJECT,
                _OPENSSL_EXTENSION_FLAG,
                _OPENSSL_BASE_CONSTRAINT,
                _OPENSSL_EXTENSION_FLAG,
                _OPENSSL_KEY_USAGE,
                _OPENSSL_EXTENSION_FLAG,
                _OPENSSL_EXTENDED_USAGE,
            )
        )
        _require_success(generated, _AUTHORITY_FAILURE)
        private_key.chmod(0o600)
        exported = _run_command(
            (
                _OPENSSL,
                _OPENSSL_PKCS12_ACTION,
                _OPENSSL_EXPORT_FLAG,
                _OPENSSL_CERTIFICATE_PBE_FLAG,
                _P12_CERTIFICATE_PBE,
                _OPENSSL_KEY_PBE_FLAG,
                _P12_KEY_PBE,
                _OPENSSL_MAC_ALGORITHM_FLAG,
                _P12_MAC_ALGORITHM,
                _OPENSSL_KEY_INPUT_FLAG,
                str(private_key),
                _OPENSSL_INPUT_FLAG,
                str(certificate),
                _OPENSSL_NAME_FLAG,
                _CERTIFICATE_LABEL,
                _OPENSSL_CERTIFICATE_OUTPUT_FLAG,
                str(authority_bundle),
                _OPENSSL_PASSWORD_OUTPUT_FLAG,
                _OPENSSL_PASSWORD_FILE_PREFIX + str(import_password),
            )
        )
        _require_success(exported, _AUTHORITY_FAILURE)
        imported = _run_security_script(
            (
                (
                    _SECURITY_IMPORT,
                    str(authority_bundle),
                    _SECURITY_KEYCHAIN_FLAG,
                    str(target_keychain),
                    _SECURITY_IMPORT_PASSWORD_FLAG,
                    password,
                    _SECURITY_TRUSTED_TOOL_FLAG,
                    _SIGNING_TOOL,
                    _SECURITY_TRUSTED_TOOL_FLAG,
                    _SECURITY_TOOL,
                ),
                (
                    _SECURITY_SET_PARTITION_LIST,
                    _SECURITY_PARTITION_FLAG,
                    _SIGNING_PARTITIONS,
                    _SECURITY_SIGNING_USE_FLAG,
                    _SECURITY_LABEL_FLAG,
                    _CERTIFICATE_LABEL,
                    _SECURITY_PARTITION_PASSWORD_FLAG,
                    secret,
                    str(target_keychain),
                ),
            )
        )
        _require_success(imported, _UNAUTHORIZED_FAILURE)
    fingerprint = authority_fingerprint(target_keychain)
    if fingerprint is None:
        raise SigningCommandError(SigningCommandKind.FAILED, _AUTHORITY_FAILURE)
    return fingerprint


def authority_fingerprint(keychain: Path | None = None) -> str | None:
    """Return the unique machine authority fingerprint from its dedicated store."""
    target = keychain or launcher_keychain_path()
    result = _run_command((_SECURITY, _SECURITY_FIND_CERTIFICATE, _SECURITY_ALL_FLAG, _SECURITY_HASH_FLAG, str(target)))
    _require_success(result, _STORE_FAILURE)
    fingerprints = [match.group(1).upper() for match in _CERTIFICATE_HASH_PATTERN.finditer(result.stdout)]
    matching = [fingerprint for fingerprint in fingerprints if fingerprint]
    if not matching:
        return None
    if len(matching) != 1:
        raise SigningCommandError(SigningCommandKind.FAILED, _AUTHORITY_FAILURE)
    return matching[0]


def authority_ready(secret: str, *, keychain: Path | None = None) -> tuple[str, bool, bool, bool]:
    """Open the store and report fingerprint, expiry and unattended key access."""
    target = keychain or launcher_keychain_path()
    unlocked = _run_security_script(((_SECURITY_UNLOCK_KEYCHAIN, _SECURITY_PASSWORD_FLAG, secret, str(target)),))
    if unlocked.returncode != 0:
        raise SigningCommandError(SigningCommandKind.FAILED, _SECRET_FAILURE)
    fingerprint = authority_fingerprint(target)
    if fingerprint is None:
        raise SigningCommandError(SigningCommandKind.FAILED, _AUTHORITY_FAILURE)
    certificate = _run_command(
        (
            _SECURITY,
            _SECURITY_FIND_CERTIFICATE,
            _SECURITY_CERTIFICATE_NAME_FLAG,
            _CERTIFICATE_LABEL,
            _SECURITY_PEM_FLAG,
            str(target),
        )
    )
    _require_success(certificate, _AUTHORITY_FAILURE)
    expiry = _run_command(
        (
            _OPENSSL,
            _OPENSSL_X509_COMMAND,
            _OPENSSL_CHECK_EXPIRY_FLAG,
            _OPENSSL_ZERO_SECONDS,
            _OPENSSL_NO_OUTPUT_FLAG,
            _OPENSSL_INPUT_FLAG,
            _STDIN_PATH,
        ),
        input_text=certificate.stdout,
    )
    identity = _run_command(
        (_SECURITY, _SECURITY_FIND_IDENTITY, _SECURITY_CODE_SIGNING_POLICY, _CODE_SIGNING_POLICY, str(target))
    )
    _require_success(identity, _AUTHORITY_FAILURE)
    has_private_key = any(
        match.group(1).upper() == fingerprint and match.group(2) == _CERTIFICATE_LABEL
        for match in _CERTIFICATE_NAME_PATTERN.finditer(identity.stdout)
    )
    access = _run_command((_SECURITY, _SECURITY_DUMP_KEYCHAIN, _SECURITY_ACL_FLAG, str(target)))
    _require_success(access, _UNAUTHORIZED_FAILURE)
    has_unattended_access = _AUTHORIZATION_PATTERN.search(access.stdout) is not None
    return fingerprint, expiry.returncode == 0, has_private_key, has_unattended_access


def delete_signing_authority(fingerprint: str, secret: str, *, keychain: Path | None = None) -> None:
    """Delete one selected signing identity after explicitly opening its store."""
    target = keychain or launcher_keychain_path()
    unlocked = _run_security_script(((_SECURITY_UNLOCK_KEYCHAIN, _SECURITY_PASSWORD_FLAG, secret, str(target)),))
    _require_success(unlocked, _SECRET_FAILURE)
    deleted = _run_command((_SECURITY, _SECURITY_DELETE_IDENTITY, _SECURITY_HASH_OPTION, fingerprint, str(target)))
    _require_success(deleted, _AUTHORITY_FAILURE)


def signing_keychain_exists(*, keychain: Path | None = None) -> bool:
    """Return whether the dedicated signing store is present without opening it."""
    return (keychain or launcher_keychain_path()).is_file()


def _launcher_definitions() -> tuple[LauncherDefinition, ...]:
    expected = {target.value for target in LauncherId if target is not LauncherId.TMUX}
    present = {agent.value for agent in AgentName}
    if present != expected:
        gap = _COMMA_SPACE.join(sorted(expected.symmetric_difference(present)))
        raise SigningCommandError(SigningCommandKind.ROSTER_GAP, _ROSTER_GAP_FAILURE.format(agents=gap))
    return tuple(_DEFINITIONS[target] for target in LauncherId)


def launcher_bundle_names() -> tuple[str, ...]:
    """Return the complete launcher application roster in stable order."""
    return tuple(definition.display_name + _APP_SUFFIX for definition in _launcher_definitions())


def launcher_input_digest(project_root: Path) -> str:
    """Digest launcher source, generated configuration, roster, plist fields and compiler version."""
    _ensure_swift_compiler()
    digest = hashlib.sha256()
    definitions = _launcher_definitions()
    source = project_root / _SOURCE_DIRECTORY / _SOURCE_FILE_NAME
    digest.update(source.read_bytes())
    for definition in definitions:
        digest.update(_BUNDLE_HASH_SEPARATOR)
        digest.update(definition.target.value.encode(_TEXT_ENCODING))
        digest.update(_BUNDLE_HASH_SEPARATOR)
        digest.update(_SWIFT_OPTIMIZATION.encode(_TEXT_ENCODING))
        digest.update(_BUNDLE_HASH_SEPARATOR)
        digest.update(_render_configuration(definition, _candidates_for(definition)).encode(_TEXT_ENCODING))
        digest.update(_BUNDLE_HASH_SEPARATOR)
        digest.update(plistlib.dumps(_launcher_plist(definition)))
    version = _run_command((_SWIFTC, _SWIFT_VERSION_FLAG))
    _require_success(version, _COMPILE_FAILURE, SigningCommandKind.COMPILE_FAILED)
    digest.update(_BUNDLE_HASH_SEPARATOR)
    digest.update(version.stdout.encode(_TEXT_ENCODING))
    return digest.hexdigest()


def _render_configuration(definition: LauncherDefinition, fixed_candidates: str) -> str:
    return _CONFIGURATION_TEMPLATE.format(
        executable=definition.target_executable,
        override_keys=definition.override_keys,
        fixed_candidates=fixed_candidates,
        override_strict=definition.override_strict,
        strict_exit_code=definition.strict_exit_code,
        argv_policy=definition.argv_policy,
    )


def _launcher_plist(definition: LauncherDefinition) -> dict[str, str | bool]:
    """Build the Info.plist fields used by both the digest and emitted bundle."""
    return {
        _PLIST_NAME: definition.display_name,
        _PLIST_IDENTIFIER: definition.bundle_identifier,
        _PLIST_VERSION: definition.version,
        _PLIST_SHORT_VERSION: definition.version,
        _PLIST_EXECUTABLE: definition.executable,
        _PLIST_PACKAGE_TYPE: _PLIST_APPLICATION,
        _PLIST_UI_ELEMENT: True,
    }


def compile_launcher_set(project_root: Path, staging_root: Path) -> tuple[Path, ...]:
    """Compile every canonical launcher into a fresh staging directory."""
    if sys.platform != _DARWIN_PLATFORM:
        return ()
    _ensure_swift_compiler()
    definitions = _launcher_definitions()
    source_file = project_root / _SOURCE_DIRECTORY / _SOURCE_FILE_NAME
    staging_root.mkdir(parents=True, exist_ok=True)
    applications: list[Path] = []
    for definition in definitions:
        application = staging_root / (definition.display_name + _APP_SUFFIX)
        executable_path = application / _CONTENTS_DIRECTORY / _EXECUTABLE_DIRECTORY / definition.executable
        executable_path.parent.mkdir(parents=True, exist_ok=True)
        configuration = staging_root / (definition.target.value + _GENERATED_SWIFT_SUFFIX)
        fixed_candidates = _candidates_for(definition)
        configuration.write_text(_render_configuration(definition, fixed_candidates), encoding=_TEXT_ENCODING)
        # swiftc has no Python binding; keep each native compiler invocation bounded.
        compiled = _run_command(
            (
                _SWIFTC,
                _SWIFT_OPTIMIZATION,
                _SWIFTC_OUTPUT_FLAG,
                str(executable_path),
                str(source_file),
                str(configuration),
            )
        )
        _require_success(compiled, _COMPILE_FAILURE, SigningCommandKind.COMPILE_FAILED)
        executable_path.chmod(0o755)
        plist_path = application / _CONTENTS_DIRECTORY / _INFO_PLIST
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_bytes(plistlib.dumps(_launcher_plist(definition)))
        applications.append(application)
    return tuple(applications)


def _candidates_for(definition: LauncherDefinition) -> str:
    if definition.target is LauncherId.DEEPSEEK:
        npm = shutil.which(_NPM_EXECUTABLE)
        if npm is not None:
            # npm owns its effective global prefix; Python has no equivalent read of npm's configuration.
            result = _run_command((npm, _NPM_PREFIX_ACTION, _NPM_GLOBAL_FLAG))
            if result.returncode == 0:
                npm_candidate = result.stdout.strip() + _NPM_BIN_SUFFIX
                return _DOUBLE_QUOTE + npm_candidate + _DOUBLE_QUOTE + _COMMA_SPACE + _DEEPSEEK_CANDIDATES
    return definition.fixed_candidates


def sign_bundle(bundle: Path, fingerprint: str, *, keychain: Path | None = None) -> None:
    """Sign one bundle by pinned fingerprint using the explicitly named keychain."""
    definition = _definition_for_bundle(bundle)
    # codesign has no Python binding; the per-call deadline bounds any unexpected prompt.
    signed = _run_command(
        (
            _CODESIGN,
            _CODESIGN_FORCE,
            _CODESIGN_RUNTIME_FLAG,
            _CODESIGN_RUNTIME_OPTION,
            _CODESIGN_NO_TIMESTAMP_FLAG,
            _CODESIGN_KEYCHAIN_FLAG,
            str(keychain or launcher_keychain_path()),
            _CODESIGN_IDENTIFIER_FLAG,
            definition.bundle_identifier,
            _CODESIGN_SIGN_FLAG,
            fingerprint,
            str(bundle),
        )
    )
    _require_success(signed, _SIGN_FAILURE)


def verify_bundle(bundle: Path, fingerprint: str | None = None) -> LauncherSignature:
    """Strictly verify one signed launcher and return its observed identity."""
    verified = _run_command((_CODESIGN, _CODESIGN_VERIFY_FLAG, _CODESIGN_STRICT_FLAG, str(bundle)))
    if verified.returncode != 0:
        reason = verified.stderr.strip() or verified.stdout.strip() or _EMPTY_VERIFICATION_REASON
        raise SigningCommandError(
            SigningCommandKind.MISMATCH,
            _STRICT_SIGNATURE_FAILURE.format(bundle=bundle.name, reason=reason),
        )
    details = _run_command((_CODESIGN, _CODESIGN_DISPLAY_FLAG, _CODESIGN_VERBOSE_FLAG, str(bundle)))
    _require_success(details, _SIGNATURE_DETAILS_FAILURE.format(bundle=bundle.name))
    requirement = _run_command((_CODESIGN, _CODESIGN_DISPLAY_FLAG, _CODESIGN_REQUIREMENT_FLAG, str(bundle)))
    _require_success(requirement, _SIGNATURE_REQUIREMENT_FAILURE.format(bundle=bundle.name))
    observed_fingerprint = _parse_signature_fingerprint(requirement.stderr + requirement.stdout)
    identifier = _parse_signature_identifier(details.stderr + details.stdout)
    code_directory_hash = _parse_code_directory_hash(details.stderr + details.stdout)
    definition = _definition_for_bundle(bundle)
    if observed_fingerprint == _EMPTY:
        raise SigningCommandError(
            SigningCommandKind.MISMATCH, _SIGNATURE_FINGERPRINT_MISSING.format(bundle=bundle.name)
        )
    if identifier != definition.bundle_identifier:
        raise SigningCommandError(
            SigningCommandKind.MISMATCH,
            _SIGNATURE_IDENTIFIER_MISMATCH.format(
                bundle=bundle.name, observed=identifier, expected=definition.bundle_identifier
            ),
        )
    if not code_directory_hash:
        raise SigningCommandError(SigningCommandKind.MISMATCH, _SIGNATURE_HASH_MISSING.format(bundle=bundle.name))
    if fingerprint is not None and observed_fingerprint != fingerprint:
        raise SigningCommandError(
            SigningCommandKind.MISMATCH,
            _SIGNATURE_FINGERPRINT_MISMATCH.format(
                bundle=bundle.name, observed=observed_fingerprint, expected=fingerprint
            ),
        )
    return LauncherSignature(observed_fingerprint, identifier, code_directory_hash)


def _definition_for_bundle(bundle: Path) -> LauncherDefinition:
    return _definition_for_name(bundle.name)


def _definition_for_name(bundle_name: str) -> LauncherDefinition:
    return next(
        definition for definition in _launcher_definitions() if bundle_name == definition.display_name + _APP_SUFFIX
    )


def _parse_signature_fingerprint(text: str) -> str:
    match = _LEAF_PATTERN.search(text)
    return match.group(1).upper() if match else _EMPTY


def _parse_signature_identifier(text: str) -> str:
    match = _IDENTIFIER_PATTERN.search(text)
    return match.group(1) if match else _EMPTY


def _parse_code_directory_hash(text: str) -> str:
    match = _CDHASH_PATTERN.search(text)
    return match.group(1).upper() if match else _EMPTY


_SECURITY_CREATE_KEYCHAIN = "create-keychain"
_SECURITY_LIST_KEYCHAINS = "list-keychains"
_SECURITY_DOMAIN_OPTION = "-d"
_SECURITY_USER_DOMAIN = "user"
_SECURITY_SET_LIST_OPTION = "-s"
_SECURITY_UNLOCK_KEYCHAIN = "unlock-keychain"
_SECURITY_KEYCHAIN_SETTINGS = "set-keychain-settings"
_SECURITY_LOCK_FLAG = "-lut"
_SECURITY_PASSWORD_FLAG = "-p"
_SECURITY_PARTITION_PASSWORD_FLAG = "-k"
_SECURITY_IMPORT = "import"
_SECURITY_KEYCHAIN_FLAG = "-k"
_SECURITY_IMPORT_PASSWORD_FLAG = "-P"
_SECURITY_TRUSTED_TOOL_FLAG = "-T"
_SECURITY_SET_PARTITION_LIST = "set-key-partition-list"
_SECURITY_PARTITION_FLAG = "-S"
_SECURITY_SIGNING_USE_FLAG = "-s"
_SECURITY_LABEL_FLAG = "-l"
_SECURITY_CERTIFICATE_NAME_FLAG = "-c"
_SECURITY_FIND_CERTIFICATE = "find-certificate"
_SECURITY_ALL_FLAG = "-a"
_SECURITY_HASH_FLAG = "-Z"
_SECURITY_PEM_FLAG = "-p"
_SECURITY_FIND_IDENTITY = "find-identity"
_SECURITY_CODE_SIGNING_POLICY = "-p"
_SECURITY_DUMP_KEYCHAIN = "dump-keychain"
_SECURITY_ACL_FLAG = "-a"
_CODESIGN_FORCE = "--force"
_CODESIGN_RUNTIME_FLAG = "--options"
_CODESIGN_RUNTIME_OPTION = "runtime"
_CODESIGN_NO_TIMESTAMP_FLAG = "--timestamp=none"
_CODESIGN_KEYCHAIN_FLAG = "--keychain"
_CODESIGN_IDENTIFIER_FLAG = "--identifier"
_CODESIGN_SIGN_FLAG = "--sign"
_CODESIGN_VERIFY_FLAG = "--verify"
_CODESIGN_STRICT_FLAG = "--strict"
_CODESIGN_DISPLAY_FLAG = "-d"
_CODESIGN_VERBOSE_FLAG = "-vvv"
_CODESIGN_REQUIREMENT_FLAG = "-r-"
_SOURCE_DIRECTORY = "src" + os.sep + "Launcher"
_APP_SUFFIX = ".app"
_GENERATED_SWIFT_SUFFIX = ".generated.swift"
_DARWIN_PLATFORM = "darwin"
_NPM_EXECUTABLE = "npm"
_NPM_BIN_SUFFIX = "/bin/dsh"
_BUNDLE_HASH_SEPARATOR = b"\0"
_SWIFT_VERSION_FLAG = "--version"
_SECURITY_DELETE_IDENTITY = "delete-identity"
_SECURITY_HASH_OPTION = "-Z"
_COMMA_SPACE = ", "
_CONFIGURATION_TEMPLATE = (
    "let launcherConfig = LauncherConfig(\n"
    '    targetExecutable: "{executable}",\n'
    "    overrideKeys: [{override_keys}],\n"
    "    fixedCandidates: [{fixed_candidates}],\n"
    "    overrideStrict: {override_strict},\n"
    "    strictExitCode: {strict_exit_code},\n"
    "    argvPolicy: {argv_policy}\n"
    ")\n"
)
_COMPILE_FAILURE = "launcher compilation failed"
_SIGN_FAILURE = "launcher signing failed"
