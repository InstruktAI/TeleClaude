"""Run Codex against immutable release evidence under a native read-only profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from tools.release.attempt import ProviderAttempt, ProviderFailure, ProviderName, ProviderOutcome
from tools.release.codex_auth import CODEX_AUTH_FILENAME, auth_secret_values
from tools.release.evidence_contract import PROMPT_FILENAME, REPORT_SCHEMA_FILENAME
from tools.release.isolated_inspection import (
    InspectorBoundaryError,
    InspectorRole,
    IsolatedProcessResult,
    install_principal_file,
    make_read_only_tree,
    read_principal_file,
    run_isolated_process,
    validate_principal_file,
    validate_principal_file_absent,
)
from tools.release.report_models import LaneReport

_CODEX_PROFILE_NAME = "release-inspector"
_CODEX_PROFILE_FILE = "release-inspector.config.toml"
_CODEX_ENVIRONMENT_HOME = "HOME"
_CODEX_ENVIRONMENT_PATH = "PATH"
_CODEX_ENVIRONMENT_TEMP = "TMPDIR"
_CODEX_ENVIRONMENT_HOME_DIR = "CODEX_HOME"
_LANGUAGE_ENVIRONMENT = "LANG"
_LC_ALL_ENVIRONMENT = "LC_ALL"
_LANGUAGE_VALUE = "C.UTF-8"
_SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
_CONFIG_ENCODING = "utf-8"
_CONFIG_NEWLINE = "\n"
SINGLE_LINE = "\n"
_TOML_DEFAULT_PROFILE = 'default_permissions = "release-inspector"'
_TOML_AUTH_STORAGE = 'cli_auth_credentials_store = "file"'
_TOML_FILESYSTEM_TABLE = "[permissions.release-inspector.filesystem]"
_TOML_NETWORK_TABLE = "[permissions.release-inspector.network]"
_TOML_ROOT_DENY = '":root" = "deny"'
_TOML_MINIMAL_READ = '":minimal" = "read"'
_TOML_TEMP_DENY = '":tmpdir" = "deny"'
_TOML_SLASH_TEMP_DENY = '":slash_tmp" = "deny"'
_TOML_PROC_DENY = '"/proc" = "deny"'
_TOML_RUN_DENY = '"/run" = "deny"'
_TOML_VAR_RUN_DENY = '"/var/run" = "deny"'
_TOML_READ_PERMISSION = "read"
_TOML_DENY_PERMISSION = "deny"
_TOML_NETWORK_DISABLED = "enabled = false"
_CODEX_EPHEMERAL_FLAG = "--ephemeral"
_CODEX_STRICT_CONFIG_FLAG = "--strict-config"
_CODEX_SKIP_REPOSITORY_FLAG = "--skip-git-repo-check"
_CODEX_IGNORE_RULES_FLAG = "--ignore-rules"
_CODEX_JSON_FLAG = "--json"
_CODEX_OUTPUT_SCHEMA_FLAG = "--output-schema"
_CODEX_OUTPUT_LAST_MESSAGE_FLAG = "--output-last-message"
_CODEX_PROFILE_FLAG = "--profile"
_REPORT_FILENAME = "codex-report.json"
_CLIENT_REPORT_FILENAME = "release-report.json"
_CODEX_EVENT_LOG_FILENAME = "codex-events.jsonl"
_STDOUT_DIAGNOSTIC_FILENAME = "codex.stdout"
_STDERR_DIAGNOSTIC_FILENAME = "codex.stderr"
_DIAGNOSTICS_DIRECTORY = "diagnostics"
_REPORT_DIRECTORY = "reports"
_REDACTION = "[redacted]"
_EMPTY = ""
_BACKSLASH_REPLACE = "backslashreplace"
_READ_ONLY_CONFIG_MODE = "400"
_PRIVATE_RESULT_DIRECTORY_MODE = 0o700
_PRIVATE_RESULT_FILE_MODE = 0o600
_TOML_ASSIGNMENT = " = "
_CODEX_DIAGNOSTIC_PATH = "diagnostics/"
_PRIVATE_PATH_REPLACEMENTS = (
    "<evidence>",
    "<controller-state>",
    "<codex-home>",
    "<inspector-home>",
    "<inspector-temp>",
)
_RESULT_PATH_EXISTS = "A Codex result artifact already exists at its destination."
_REPORT_FILE_PATH = "reports/codex-report.json"
_DIAGNOSTIC_EXIT_CODE = "Codex CLI exited without a valid complete assessment."
_DIAGNOSTIC_TIMEOUT = "Codex CLI exceeded its bounded execution time."
_DIAGNOSTIC_INVALID_REPORT = "Codex CLI returned a report that did not match its declared schema."
_DIAGNOSTIC_INCOMPLETE = "Codex returned a structurally valid incomplete assessment."
_DIAGNOSTIC_SETUP_FAILURE = "Codex inspection setup or execution failed before a valid assessment."
_DIAGNOSTIC_AUTH_STATE_FAILURE = "Codex auth state could not be captured after the isolated process exited."
_CONFIGURATION_INVALID = "The private Codex inspection configuration is unavailable or unsafe."
_STDOUT_HASH_PREFIX = "stdout_sha256="
_STDERR_HASH_PREFIX = "stderr_sha256="


class InspectionRunResult(BaseModel):
    """One provider result, with a valid report separated from execution diagnostics."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempt: ProviderAttempt
    report: LaneReport | None
    report_path: str | None


def run_codex_inspection(
    executable: Path,
    evidence_directory: Path,
    controller_directory: Path,
    principal_home: Path,
    principal_temp: Path,
    codex_home: Path,
    result_directory: Path,
    auth_json_before: bytes,
    timeout_seconds: int,
    *,
    runtime_path: str = _SYSTEM_PATH,
) -> InspectionRunResult:
    """Run a single schema-constrained Codex assessment in a dedicated UID."""
    if result_directory.exists() or result_directory.is_symlink():
        raise ValueError(_RESULT_PATH_EXISTS)
    result_directory.mkdir(mode=_PRIVATE_RESULT_DIRECTORY_MODE, parents=True)
    make_read_only_tree(evidence_directory)
    validate_codex_configuration(evidence_directory, controller_directory, principal_home, principal_temp, codex_home)
    client_report = codex_home / _CLIENT_REPORT_FILENAME
    validate_principal_file_absent(InspectorRole.CODEX, controller_directory, client_report)
    prompt = (evidence_directory / PROMPT_FILENAME).read_bytes()
    schema_path = evidence_directory / REPORT_SCHEMA_FILENAME
    environment = {
        _CODEX_ENVIRONMENT_HOME: str(principal_home),
        _CODEX_ENVIRONMENT_PATH: runtime_path,
        _CODEX_ENVIRONMENT_TEMP: str(principal_temp),
        _CODEX_ENVIRONMENT_HOME_DIR: str(codex_home),
        _LANGUAGE_ENVIRONMENT: _LANGUAGE_VALUE,
        _LC_ALL_ENVIRONMENT: _LANGUAGE_VALUE,
    }
    arguments = (
        _CODEX_EPHEMERAL_FLAG,
        _CODEX_STRICT_CONFIG_FLAG,
        _CODEX_SKIP_REPOSITORY_FLAG,
        _CODEX_IGNORE_RULES_FLAG,
        _CODEX_PROFILE_FLAG,
        _CODEX_PROFILE_NAME,
        _CODEX_JSON_FLAG,
        _CODEX_OUTPUT_SCHEMA_FLAG,
        str(schema_path),
        _CODEX_OUTPUT_LAST_MESSAGE_FLAG,
        str(client_report),
    )
    try:
        result = run_isolated_process(
            InspectorRole.CODEX,
            executable,
            arguments,
            evidence_directory,
            environment,
            controller_directory=controller_directory,
            stdin=prompt,
            timeout_seconds=timeout_seconds,
        )
    except InspectorBoundaryError:
        raise
    except (OSError, RuntimeError, ValueError):
        return _failed_result(ProviderFailure.EXECUTION, None, False, _DIAGNOSTIC_SETUP_FAILURE, result_directory)
    try:
        final_message = read_principal_file(InspectorRole.CODEX, client_report)
        auth_json_after = read_principal_file(InspectorRole.CODEX, codex_home / CODEX_AUTH_FILENAME)
        auth_secret_values(auth_json_after)
    except (OSError, RuntimeError, ValueError):
        final_message = _EMPTY.encode(_CONFIG_ENCODING)
        auth_json_after = None
    return _interpret_result(
        result,
        final_message,
        auth_json_before,
        auth_json_after,
        result_directory,
        (evidence_directory, controller_directory, codex_home, principal_home, principal_temp),
    )


def prepare_codex_configuration(evidence: Path, controller: Path, home: Path, temporary: Path, config: Path) -> None:
    """Stage the unchanged private permission profile before the auth-use checkpoint."""
    profile = _profile_content(evidence, controller, home, temporary, config)
    install_principal_file(
        InspectorRole.CODEX,
        controller,
        config / _CODEX_PROFILE_FILE,
        profile.encode(_CONFIG_ENCODING),
        mode=_READ_ONLY_CONFIG_MODE,
    )


def validate_codex_configuration(evidence: Path, controller: Path, home: Path, temporary: Path, config: Path) -> None:
    """Validate metadata and exact permission-profile bytes without following provider links."""
    path = config / _CODEX_PROFILE_FILE
    validate_principal_file(InspectorRole.CODEX, controller, path, mode=_READ_ONLY_CONFIG_MODE)
    expected = _profile_content(evidence, controller, home, temporary, config).encode(_CONFIG_ENCODING)
    if read_principal_file(InspectorRole.CODEX, path) != expected:
        raise ValueError(_CONFIGURATION_INVALID)


def _interpret_result(
    process: IsolatedProcessResult,
    final_message: bytes,
    auth_json_before: bytes,
    auth_json_after: bytes | None,
    result_directory: Path,
    private_paths: tuple[Path, ...],
) -> InspectionRunResult:
    """Classify only structured process outcomes and the typed report schema."""
    if auth_json_after is None:
        diagnostic = _write_diagnostic(
            result_directory,
            _STDERR_DIAGNOSTIC_FILENAME,
            (
                _DIAGNOSTIC_AUTH_STATE_FAILURE
                + SINGLE_LINE
                + _STDOUT_HASH_PREFIX
                + hashlib.sha256(process.stdout).hexdigest()
                + SINGLE_LINE
                + _STDERR_HASH_PREFIX
                + hashlib.sha256(process.stderr).hexdigest()
            ).encode(_CONFIG_ENCODING),
        )
        return _failed_result(
            ProviderFailure.AUTH_SETTLEMENT,
            process.return_code,
            process.timed_out,
            _DIAGNOSTIC_AUTH_STATE_FAILURE,
            result_directory,
            diagnostic,
        )
    auth_json_values = (auth_json_before, auth_json_after)
    event_log = _write_diagnostic(
        result_directory,
        _CODEX_EVENT_LOG_FILENAME,
        _safe_diagnostic(process.stdout, auth_json_values, private_paths),
    )
    if process.timed_out:
        diagnostic = _write_diagnostic(
            result_directory,
            _STDERR_DIAGNOSTIC_FILENAME,
            _safe_diagnostic(process.stderr, auth_json_values, private_paths),
        )
        return _failed_result(
            ProviderFailure.AVAILABILITY, process.return_code, True, _DIAGNOSTIC_TIMEOUT, result_directory, diagnostic
        )
    if process.return_code != 0:
        diagnostic = _write_diagnostic(
            result_directory,
            _STDERR_DIAGNOSTIC_FILENAME,
            _safe_diagnostic(process.stderr, auth_json_values, private_paths),
        )
        return _failed_result(
            ProviderFailure.EXECUTION, process.return_code, False, _DIAGNOSTIC_EXIT_CODE, result_directory, diagnostic
        )
    try:
        report = LaneReport.model_validate_json(final_message)
    except ValidationError:
        diagnostic = _write_diagnostic(
            result_directory,
            _STDOUT_DIAGNOSTIC_FILENAME,
            _safe_diagnostic(final_message, auth_json_values, private_paths),
        )
        return _failed_result(
            ProviderFailure.INVALID_REPORT,
            process.return_code,
            False,
            _DIAGNOSTIC_INVALID_REPORT,
            result_directory,
            diagnostic,
        )
    report_bytes = report.model_dump_json().encode(_CONFIG_ENCODING)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    if not report.assessment_complete:
        diagnostic = _write_diagnostic(
            result_directory,
            _STDOUT_DIAGNOSTIC_FILENAME,
            _safe_diagnostic(final_message, auth_json_values, private_paths),
        )
        report_path = _write_report(result_directory, report_bytes)
        return InspectionRunResult(
            attempt=ProviderAttempt(
                provider=ProviderName.CODEX,
                outcome=ProviderOutcome.FAILED,
                failure=ProviderFailure.INCOMPLETE,
                report_sha256=report_sha256,
                auth_settled=False,
                exit_code=process.return_code,
                timed_out=False,
                diagnostic_path=diagnostic,
            ),
            report=report,
            report_path=report_path,
        )
    report_path = _write_report(result_directory, report_bytes)
    return InspectionRunResult(
        attempt=ProviderAttempt(
            provider=ProviderName.CODEX,
            outcome=ProviderOutcome.SUCCEEDED,
            failure=None,
            report_sha256=report_sha256,
            auth_settled=False,
            exit_code=process.return_code,
            timed_out=False,
            diagnostic_path=event_log,
        ),
        report=report,
        report_path=report_path,
    )


def _failed_result(
    failure: ProviderFailure,
    return_code: int | None,
    timed_out: bool,
    message: str,
    result_directory: Path,
    diagnostic_path: str | None = None,
) -> InspectionRunResult:
    """Record a typed provider failure without using diagnostic prose as a classifier."""
    if diagnostic_path is None:
        diagnostic_path = _write_diagnostic(
            result_directory,
            _STDERR_DIAGNOSTIC_FILENAME,
            message.encode(_CONFIG_ENCODING),
        )
    return InspectionRunResult(
        attempt=ProviderAttempt(
            provider=ProviderName.CODEX,
            outcome=ProviderOutcome.FAILED,
            failure=failure,
            report_sha256=None,
            auth_settled=False,
            exit_code=return_code,
            timed_out=timed_out,
            diagnostic_path=diagnostic_path,
        ),
        report=None,
        report_path=None,
    )


def _profile_content(
    evidence_directory: Path,
    controller_directory: Path,
    principal_home: Path,
    principal_temp: Path,
    codex_home: Path,
) -> str:
    """Build a native Codex read-only profile that exposes only the evidence tree."""
    lines = (
        _TOML_DEFAULT_PROFILE,
        _TOML_AUTH_STORAGE,
        _TOML_FILESYSTEM_TABLE,
        _TOML_ROOT_DENY,
        _TOML_MINIMAL_READ,
        _TOML_TEMP_DENY,
        _TOML_SLASH_TEMP_DENY,
        _TOML_PROC_DENY,
        _TOML_RUN_DENY,
        _TOML_VAR_RUN_DENY,
        _toml_path_rule(evidence_directory, _TOML_READ_PERMISSION),
        _toml_path_rule(codex_home, _TOML_DENY_PERMISSION),
        _toml_path_rule(controller_directory, _TOML_DENY_PERMISSION),
        _toml_path_rule(principal_home, _TOML_DENY_PERMISSION),
        _toml_path_rule(principal_temp, _TOML_DENY_PERMISSION),
        _TOML_NETWORK_TABLE,
        _TOML_NETWORK_DISABLED,
    )
    return _CONFIG_NEWLINE.join(lines) + _CONFIG_NEWLINE


def _toml_path_rule(path: Path, permission: str) -> str:
    """Render one absolute TOML filesystem rule without changing path meaning."""
    return json.dumps(str(path.resolve())) + _TOML_ASSIGNMENT + json.dumps(permission)


def _safe_diagnostic(
    content: bytes,
    auth_json_values: tuple[bytes, ...],
    private_paths: tuple[Path, ...],
) -> bytes:
    """Remove known credentials and local machine paths from provider diagnostics."""
    text = content.decode(_CONFIG_ENCODING, errors=_BACKSLASH_REPLACE)
    for auth_json in auth_json_values:
        for secret in auth_secret_values(auth_json):
            if secret:
                text = text.replace(secret, _REDACTION)
    for path, replacement in zip(private_paths, _PRIVATE_PATH_REPLACEMENTS, strict=True):
        text = text.replace(str(path), replacement)
    return text.encode(_CONFIG_ENCODING)


def _write_report(result_directory: Path, report_bytes: bytes) -> str:
    """Write a validated report under the controller-owned report artifact root."""
    report_directory = result_directory / _REPORT_DIRECTORY
    report_directory.mkdir(mode=_PRIVATE_RESULT_DIRECTORY_MODE, parents=True, exist_ok=True)
    path = report_directory / _REPORT_FILENAME
    if path.exists() or path.is_symlink():
        raise ValueError(_RESULT_PATH_EXISTS)
    path.write_bytes(report_bytes)
    path.chmod(_PRIVATE_RESULT_FILE_MODE)
    return _REPORT_FILE_PATH


def _write_diagnostic(result_directory: Path, filename: str, content: bytes) -> str:
    """Persist one sanitized process diagnostic for the workflow artifact."""
    if result_directory.is_symlink():
        raise ValueError(_RESULT_PATH_EXISTS)
    result_directory.mkdir(mode=_PRIVATE_RESULT_DIRECTORY_MODE, parents=True, exist_ok=True)
    diagnostic_directory = result_directory / _DIAGNOSTICS_DIRECTORY
    diagnostic_directory.mkdir(mode=_PRIVATE_RESULT_DIRECTORY_MODE, parents=True, exist_ok=True)
    path = diagnostic_directory / filename
    if path.exists() or path.is_symlink():
        raise ValueError(_RESULT_PATH_EXISTS)
    path.write_bytes(content)
    path.chmod(_PRIVATE_RESULT_FILE_MODE)
    return _CODEX_DIAGNOSTIC_PATH + filename
