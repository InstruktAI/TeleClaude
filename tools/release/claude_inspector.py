"""Run Claude subscription inspection with only restricted native file-read tools."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, ValidationError

from tools.release.attempt import ProviderAttempt, ProviderFailure, ProviderName, ProviderOutcome, ReleaseDecisionMode
from tools.release.evidence_contract import PROMPT_FILENAME
from tools.release.isolated_inspection import (
    InspectorBoundaryError,
    InspectorRole,
    IsolatedProcessResult,
    install_principal_file,
    make_read_only_tree,
    read_principal_file,
    run_isolated_process,
    validate_principal_file,
)
from tools.release.report_models import InspectorReport, report_complete, report_model

_CLAUDE_AUTH_TOKEN_ENVIRONMENT = "CLAUDE_CODE_OAUTH_TOKEN"
_CLAUDE_CONFIG_ENVIRONMENT = "CLAUDE_CONFIG_DIR"
_HOME_ENVIRONMENT = "HOME"
_PATH_ENVIRONMENT = "PATH"
_TEMP_ENVIRONMENT = "TMPDIR"
_LANG_ENVIRONMENT = "LANG"
_LC_ALL_ENVIRONMENT = "LC_ALL"
_LANGUAGE_VALUE = "C.UTF-8"
_SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"
_CONFIG_ENCODING = "utf-8"
_JSON_INDENT = 2
_JSON_ENSURE_ASCII = True
_JSON_SCHEMA_SEPARATOR = (",", ":")
_PRINT_FLAG = "-p"
_RESTRICTED_FLAG = "--restricted"
_SAFE_MODE_FLAG = "--safe-mode"
_PERMISSION_MODE_FLAG = "--permission-mode"
_DONT_ASK_MODE = "dontAsk"
_PERMISSION_PROMPTS_FLAG = "--permission-prompts"
_NO_PERMISSION_PROMPTS = "none"
_NO_SESSION_PERSISTENCE_FLAG = "--no-session-persistence"
_STRICT_MCP_CONFIG_FLAG = "--strict-mcp-config"
_MCP_CONFIG_FLAG = "--mcp-config"
_EMPTY_MCP_CONFIG = '{"mcpServers":{}}'
_TOOLS_FLAG = "--tools"
_READ_TOOLS = "Read,Glob,Grep"
_DISALLOWED_TOOLS_FLAG = "--disallowedTools"
_DISALLOWED_MCP_TOOLS = "mcp__*"
_MAX_TURNS_FLAG = "--max-turns"
_OUTPUT_FORMAT_FLAG = "--output-format"
_STREAM_JSON_OUTPUT_FORMAT = "stream-json"
_VERBOSE_FLAG = "--verbose"
_INCLUDE_HOOK_EVENTS_FLAG = "--include-hook-events"
_JSON_SCHEMA_FLAG = "--json-schema"
_SETTINGS_FLAG = "--settings"
_MAX_TURNS = "40"
_MANAGED_SETTINGS_DIRECTORY = "/etc/claude-code"
_MANAGED_SETTINGS_FILE = "managed-settings.json"
_MANAGED_SETTINGS_PARTS_DIRECTORY = "managed-settings.d"
_MANAGED_MCP_FILE = "managed-mcp.json"
_MANAGED_POLICY_MAX_BYTES = 2 * 1024 * 1024
_JSON_GLOB = "*.json"
_PERMISSIONS_KEY = "permissions"
_BLOCK_OUTSIDE_READS_KEY = "blockReadsOutsideWorkingDirectories"
_DEFAULT_MODE_KEY = "defaultMode"
_DENY_KEY = "deny"
_PROC_DIRECTORY = Path("/proc")
_RUN_DIRECTORY = Path("/run")
_SYSTEM_RUN_DIRECTORY = Path("/var/run")
_READ_RULE_PREFIX = "Read(//"
_READ_RULE_SUFFIX = "/**)"
_TRAILING_SLASH = "/"
_LEADING_SLASH = "/"
_OUTPUT_SETTINGS_FILE = "settings.json"
_READ_ONLY_CONFIG_MODE = "400"
_PRIVATE_RESULT_DIRECTORY_MODE = 0o700
_PRIVATE_RESULT_FILE_MODE = 0o600
_CLAUDE_REPORT_FILENAME = "claude-report.json"
_CLAUDE_EVENT_LOG_FILENAME = "claude-events.jsonl"
_CLAUDE_STDOUT_FILENAME = "claude.stdout"
_CLAUDE_STDERR_FILENAME = "claude.stderr"
_REPORT_DIRECTORY = "reports"
_DIAGNOSTICS_DIRECTORY = "diagnostics"
_CLAUDE_DIAGNOSTIC_PATH = "diagnostics/"
_CLAUDE_EVENT_LOG_PATH = "diagnostics/claude-events.jsonl"
_REPORT_FILE_PATH = "reports/claude-report.json"
_REDACTION = "[redacted]"
_BACKSLASH_REPLACE = "backslashreplace"
_PRIVATE_PATH_REPLACEMENTS = (
    "<evidence>",
    "<controller-state>",
    "<claude-config>",
    "<inspector-home>",
    "<inspector-temp>",
)
_RESULT_PATH_EXISTS = "A Claude result artifact already exists at its destination."
_MANAGED_POLICY_INVALID = "The effective local Claude managed policy contains unsupported settings."
_MANAGED_POLICY_MCP = "The effective local Claude policy contains an unexpected MCP server."
_MANAGED_POLICY_UNREADABLE = "The local Claude managed policy could not be read safely."
_DIAGNOSTIC_TIMEOUT = "Claude CLI exceeded its bounded execution time."
_DIAGNOSTIC_EXECUTION = "Claude CLI exited without a valid complete assessment."
_DIAGNOSTIC_INVALID_REPORT = "Claude CLI returned a report that did not match its declared schema."
_DIAGNOSTIC_INCOMPLETE = "Claude returned a structurally valid incomplete assessment."
_DIAGNOSTIC_SETUP_FAILURE = "Claude inspection setup failed before a valid assessment."
_STRUCTURED_SUCCESS = "success"
_STRUCTURED_RETRY_FAILURE = "error_max_structured_output_retries"
_WRAPPER_TYPE = "result"
_ASSISTANT_TYPE = "assistant"
_TOOL_USE_TYPE = "tool_use"
_TOOL_RESULT_TYPE = "tool_result"
_USER_TYPE = "user"
_SYSTEM_EVENT_TYPE = "system"
_STRUCTURED_OUTPUT_TOOL_NAME = "StructuredOutput"
_READ_TOOL_NAME = "Read"
_GLOB_TOOL_NAME = "Glob"
_HOOK_EVENT_SUBTYPES = frozenset({"hook_started", "hook_progress", "hook_response"})
_ALLOWED_TOOL_NAMES = frozenset({"Read", "Glob", "Grep"})
_AMBIGUOUS_ABSOLUTE_GLOB_CHARACTERS = frozenset("{}()|!\\")
_GLOB_ROOT_METACHARACTERS = _AMBIGUOUS_ABSOLUTE_GLOB_CHARACTERS | frozenset("*?[]")
_GLOB_NEGATION_PREFIX = "!"
_NULL_BYTE = "\0"
_PATH_SEPARATOR = "/"
_UNEXPECTED_HOOK_EVENT = "Claude emitted an unapproved managed hook event."
_UNEXPECTED_TOOL_EVENT = "Claude emitted a tool invocation outside its read-only allowlist."
_UNEXPECTED_TOOL_PATH = "Claude requested a file path outside the prepared evidence root."
_NO_STRUCTURED_RESULT = "Claude's stream ended without one structured result event."
_BROKEN_TOOL_CORRELATION = "Claude emitted an unconfirmed or ambiguous native tool lifecycle."
_FORMATTER_REPORT_MISMATCH = "Claude's terminal report does not match its confirmed native formatter."
_CONFIGURATION_INVALID = "The private Claude inspection configuration is unavailable or unsafe."
_EMPTY = ""
_PARENT_DIRECTORY_PART = ".."
_CURRENT_DIRECTORY_PART = "."


class ManagedPermissions(BaseModel):
    """The only harmless managed permission values admitted by the inspector preflight."""

    model_config = ConfigDict(extra="forbid", strict=True)

    deny: list[str] | None = None
    blockReadsOutsideWorkingDirectories: bool | None = None


class ManagedSettings(BaseModel):
    """File-managed settings shape accepted before a restricted Claude invocation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    permissions: ManagedPermissions | None = None


class ManagedMcpServer(BaseModel):
    """Recognized managed MCP process fields, which remain rejected when present."""

    model_config = ConfigDict(extra="ignore", strict=True)

    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None


class ManagedMcpSettings(BaseModel):
    """Machine-managed MCP settings, which must be empty for this inspector."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mcpServers: dict[str, ManagedMcpServer] | None = None


class ClaudeFileToolInput(BaseModel):
    """Documented path-bearing fields used by Claude's built-in file tools."""

    model_config = ConfigDict(extra="ignore", strict=True)

    file_path: str | None = None
    path: str | list[str] | None = None
    pattern: str | None = None


class ClaudeToolUse(BaseModel):
    """One native tool request recorded in Claude's structured event stream."""

    model_config = ConfigDict(extra="ignore", strict=True)

    type: str | None = None
    name: str | None = None
    id: str | None = None
    tool_use_id: str | None = None
    is_error: bool | None = None
    input: object | None = None


class ClaudeMessage(BaseModel):
    """Message record carrying any native tool requests."""

    model_config = ConfigDict(extra="ignore", strict=True)

    role: str | None = None
    content: list[ClaudeToolUse] | None = None


class ClaudeCliEnvelope(BaseModel):
    """Structured event record emitted by Claude's JSON print mode."""

    model_config = ConfigDict(extra="ignore", strict=True)

    type: str | None = None
    subtype: str | None = None
    is_error: bool | None = None
    structured_output: object | None = None
    session_id: str | None = None
    parent_tool_use_id: str | None = None
    message: ClaudeMessage | None = None


class ClaudeInspectionResult(BaseModel):
    """One Claude provider result with a typed report and sanitized diagnostic location."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    attempt: ProviderAttempt
    report: InspectorReport | None
    report_path: str | None


class _ClaudeStreamOutputError(ValueError):
    """The provider stream did not contain exactly one structured result event."""


def inspect_local_managed_policy(managed_directory: Path = Path(_MANAGED_SETTINGS_DIRECTORY)) -> None:
    """Reject unreadable local managed inputs and every configured executable integration."""
    if managed_directory.is_symlink():
        raise RuntimeError(_MANAGED_POLICY_UNREADABLE)
    if not managed_directory.exists():
        return
    if not managed_directory.is_dir():
        raise RuntimeError(_MANAGED_POLICY_UNREADABLE)
    settings_files = [managed_directory / _MANAGED_SETTINGS_FILE]
    parts_directory = managed_directory / _MANAGED_SETTINGS_PARTS_DIRECTORY
    if parts_directory.exists():
        if parts_directory.is_symlink() or not parts_directory.is_dir():
            raise RuntimeError(_MANAGED_POLICY_UNREADABLE)
        settings_files.extend(sorted(parts_directory.glob(_JSON_GLOB)))
    for settings_path in settings_files:
        if not settings_path.exists():
            continue
        if (
            settings_path.is_symlink()
            or not settings_path.is_file()
            or settings_path.stat().st_size > _MANAGED_POLICY_MAX_BYTES
        ):
            raise RuntimeError(_MANAGED_POLICY_UNREADABLE)
        try:
            settings = ManagedSettings.model_validate_json(settings_path.read_bytes())
        except (OSError, ValidationError):
            raise RuntimeError(_MANAGED_POLICY_INVALID) from None
        permissions = settings.permissions
        if permissions is not None and permissions.blockReadsOutsideWorkingDirectories is False:
            raise RuntimeError(_MANAGED_POLICY_INVALID)
    managed_mcp_path = managed_directory / _MANAGED_MCP_FILE
    if not managed_mcp_path.exists():
        return
    if (
        managed_mcp_path.is_symlink()
        or not managed_mcp_path.is_file()
        or managed_mcp_path.stat().st_size > _MANAGED_POLICY_MAX_BYTES
    ):
        raise RuntimeError(_MANAGED_POLICY_UNREADABLE)
    try:
        mcp_settings = ManagedMcpSettings.model_validate_json(managed_mcp_path.read_bytes())
    except (OSError, ValidationError):
        raise RuntimeError(_MANAGED_POLICY_INVALID) from None
    if mcp_settings.mcpServers:
        raise RuntimeError(_MANAGED_POLICY_MCP)


def run_claude_inspection(
    executable: Path,
    evidence_directory: Path,
    controller_directory: Path,
    principal_home: Path,
    principal_temp: Path,
    claude_config_directory: Path,
    result_directory: Path,
    oauth_token: str,
    timeout_seconds: int,
    *,
    runtime_path: str = _SYSTEM_PATH,
    decision_mode: ReleaseDecisionMode = ReleaseDecisionMode.AUTOMATIC,
) -> ClaudeInspectionResult:
    """Run one restricted Claude assessment with no shell, MCP, source write, or host credentials."""
    if not oauth_token:
        return _failed_result(ProviderFailure.EXECUTION, None, False, _DIAGNOSTIC_SETUP_FAILURE, result_directory)
    if result_directory.exists() or result_directory.is_symlink():
        raise ValueError(_RESULT_PATH_EXISTS)
    result_directory.mkdir(mode=_PRIVATE_RESULT_DIRECTORY_MODE, parents=True)
    try:
        inspect_local_managed_policy()
        make_read_only_tree(evidence_directory)
        settings_path = claude_config_directory / _OUTPUT_SETTINGS_FILE
        validate_claude_configuration(
            evidence_directory, controller_directory, principal_home, principal_temp, claude_config_directory
        )
    except (OSError, RuntimeError, ValueError):
        return _failed_result(ProviderFailure.EXECUTION, None, False, _DIAGNOSTIC_SETUP_FAILURE, result_directory)
    prompt = (evidence_directory / PROMPT_FILENAME).read_bytes()
    schema = json.dumps(
        report_model(decision_mode).model_json_schema(),
        ensure_ascii=_JSON_ENSURE_ASCII,
        separators=_JSON_SCHEMA_SEPARATOR,
    )
    environment = {
        _HOME_ENVIRONMENT: str(principal_home),
        _PATH_ENVIRONMENT: runtime_path,
        _TEMP_ENVIRONMENT: str(principal_temp),
        _CLAUDE_CONFIG_ENVIRONMENT: str(claude_config_directory),
        _CLAUDE_AUTH_TOKEN_ENVIRONMENT: oauth_token,
        _LANG_ENVIRONMENT: _LANGUAGE_VALUE,
        _LC_ALL_ENVIRONMENT: _LANGUAGE_VALUE,
    }
    arguments = (
        _PRINT_FLAG,
        _RESTRICTED_FLAG,
        _SAFE_MODE_FLAG,
        _PERMISSION_MODE_FLAG,
        _DONT_ASK_MODE,
        _PERMISSION_PROMPTS_FLAG,
        _NO_PERMISSION_PROMPTS,
        _NO_SESSION_PERSISTENCE_FLAG,
        _STRICT_MCP_CONFIG_FLAG,
        _MCP_CONFIG_FLAG,
        _EMPTY_MCP_CONFIG,
        _TOOLS_FLAG,
        _READ_TOOLS,
        _DISALLOWED_TOOLS_FLAG,
        _DISALLOWED_MCP_TOOLS,
        _MAX_TURNS_FLAG,
        _MAX_TURNS,
        _OUTPUT_FORMAT_FLAG,
        _STREAM_JSON_OUTPUT_FORMAT,
        _VERBOSE_FLAG,
        _INCLUDE_HOOK_EVENTS_FLAG,
        _JSON_SCHEMA_FLAG,
        schema,
        _SETTINGS_FLAG,
        str(settings_path),
    )
    try:
        process = run_isolated_process(
            InspectorRole.CLAUDE,
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
    return _interpret_result(
        process,
        oauth_token,
        result_directory,
        (evidence_directory, controller_directory, claude_config_directory, principal_home, principal_temp),
        decision_mode,
    )


def prepare_claude_configuration(evidence: Path, controller: Path, home: Path, temporary: Path, config: Path) -> None:
    """Stage the unchanged private native settings before credential-bearing execution."""
    inspect_local_managed_policy()
    settings = _settings_content(evidence, controller, config, home, temporary)
    install_principal_file(
        InspectorRole.CLAUDE, controller, config / _OUTPUT_SETTINGS_FILE, settings, mode=_READ_ONLY_CONFIG_MODE
    )


def validate_claude_configuration(evidence: Path, controller: Path, home: Path, temporary: Path, config: Path) -> None:
    """Validate contained settings metadata and bytes, keeping configuration policy with this adapter."""
    path = config / _OUTPUT_SETTINGS_FILE
    validate_principal_file(InspectorRole.CLAUDE, controller, path, mode=_READ_ONLY_CONFIG_MODE)
    if read_principal_file(InspectorRole.CLAUDE, path) != _settings_content(
        evidence, controller, config, home, temporary
    ):
        raise ValueError(_CONFIGURATION_INVALID)


def _interpret_result(
    process: IsolatedProcessResult,
    oauth_token: str,
    result_directory: Path,
    private_paths: tuple[Path, ...],
    decision_mode: ReleaseDecisionMode = ReleaseDecisionMode.AUTOMATIC,
) -> ClaudeInspectionResult:
    """Read a structured CLI envelope and validate only its declared report model."""
    event_log = _write_diagnostic(
        result_directory,
        _CLAUDE_EVENT_LOG_FILENAME,
        _safe_diagnostic(process.stdout, oauth_token, private_paths),
    )
    if process.timed_out:
        diagnostic = _write_diagnostic(
            result_directory,
            _CLAUDE_STDERR_FILENAME,
            _safe_diagnostic(process.stderr, oauth_token, private_paths),
        )
        return _failed_result(
            ProviderFailure.AVAILABILITY, process.return_code, True, _DIAGNOSTIC_TIMEOUT, result_directory, diagnostic
        )
    try:
        response = _parse_stream_result(process.stdout, private_paths[0], decision_mode)
    except (ValidationError, _ClaudeStreamOutputError):
        if process.return_code != 0:
            diagnostic = _write_diagnostic(
                result_directory,
                _CLAUDE_STDERR_FILENAME,
                _safe_diagnostic(process.stderr, oauth_token, private_paths),
            )
            return _failed_result(
                ProviderFailure.EXECUTION,
                process.return_code,
                False,
                _DIAGNOSTIC_EXECUTION,
                result_directory,
                diagnostic,
            )
        return _invalid_report(process, oauth_token, result_directory, private_paths)
    if response.subtype == _STRUCTURED_RETRY_FAILURE:
        diagnostic = _write_diagnostic(
            result_directory,
            _CLAUDE_STDOUT_FILENAME,
            _safe_diagnostic(process.stdout, oauth_token, private_paths),
        )
        return _failed_result(
            ProviderFailure.INVALID_REPORT,
            process.return_code,
            False,
            _DIAGNOSTIC_INVALID_REPORT,
            result_directory,
            diagnostic,
        )
    if response.is_error is True:
        diagnostic = _write_diagnostic(
            result_directory,
            _CLAUDE_STDERR_FILENAME,
            _safe_diagnostic(process.stderr, oauth_token, private_paths),
        )
        return _failed_result(
            ProviderFailure.EXECUTION,
            process.return_code,
            False,
            _DIAGNOSTIC_EXECUTION,
            result_directory,
            diagnostic,
        )
    if process.return_code != 0:
        diagnostic = _write_diagnostic(
            result_directory,
            _CLAUDE_STDERR_FILENAME,
            _safe_diagnostic(process.stderr, oauth_token, private_paths),
        )
        return _failed_result(
            ProviderFailure.EXECUTION, process.return_code, False, _DIAGNOSTIC_EXECUTION, result_directory, diagnostic
        )
    try:
        if response.type == _WRAPPER_TYPE:
            if response.subtype != _STRUCTURED_SUCCESS or response.structured_output is None:
                return _invalid_report(process, oauth_token, result_directory, private_paths)
            report = report_model(decision_mode).model_validate(response.structured_output)
        else:
            report = report_model(decision_mode).model_validate_json(process.stdout)
    except ValidationError:
        return _invalid_report(process, oauth_token, result_directory, private_paths)
    report_bytes = report.model_dump_json().encode(_CONFIG_ENCODING)
    report_digest = hashlib.sha256(report_bytes).hexdigest()
    if not report_complete(report):
        diagnostic = _write_diagnostic(
            result_directory,
            _CLAUDE_STDOUT_FILENAME,
            _safe_diagnostic(process.stdout, oauth_token, private_paths),
        )
        report_path = _write_report(result_directory, report_bytes)
        return ClaudeInspectionResult(
            attempt=ProviderAttempt(
                provider=ProviderName.CLAUDE,
                outcome=ProviderOutcome.FAILED,
                failure=ProviderFailure.INCOMPLETE,
                report_sha256=report_digest,
                auth_settled=True,
                exit_code=process.return_code,
                timed_out=False,
                diagnostic_path=diagnostic,
            ),
            report=report,
            report_path=report_path,
        )
    report_path = _write_report(result_directory, report_bytes)
    return ClaudeInspectionResult(
        attempt=ProviderAttempt(
            provider=ProviderName.CLAUDE,
            outcome=ProviderOutcome.SUCCEEDED,
            failure=None,
            report_sha256=report_digest,
            auth_settled=True,
            exit_code=process.return_code,
            timed_out=False,
            diagnostic_path=event_log,
        ),
        report=report,
        report_path=report_path,
    )


class NativeToolRequest(BaseModel):
    """One pending native request with its original context and opaque input."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    invocation: ClaudeToolUse
    session_id: str
    parent_tool_use_id: str | None


def _parse_stream_result(
    output: bytes, evidence_directory: Path, decision_mode: ReleaseDecisionMode = ReleaseDecisionMode.AUTOMATIC
) -> ClaudeCliEnvelope:
    """Correlate native outcomes without forgiving unsafe requests or malformed accepted output."""
    results: list[ClaudeCliEnvelope] = []
    pending: dict[str, NativeToolRequest] = {}
    seen: set[str] = set()
    confirmed: dict[tuple[str, str | None], InspectorReport] = {}
    for line in output.splitlines():
        if not line:
            continue
        event = ClaudeCliEnvelope.model_validate_json(line)
        if event.type == _SYSTEM_EVENT_TYPE and event.subtype in _HOOK_EVENT_SUBTYPES:
            raise InspectorBoundaryError(_UNEXPECTED_HOOK_EVENT)
        for block in event.message.content or [] if event.message is not None else []:
            if block.type == _TOOL_USE_TYPE:
                if (
                    results
                    or event.type != _ASSISTANT_TYPE
                    or event.message is None
                    or event.message.role != _ASSISTANT_TYPE
                    or not event.session_id
                    or not block.id
                    or block.id in seen
                ):
                    raise InspectorBoundaryError(_BROKEN_TOOL_CORRELATION)
                # Every capability other than report formatting is judged at request time, even on failure.
                if block.name != _STRUCTURED_OUTPUT_TOOL_NAME:
                    _validate_tool_invocation(block, evidence_directory, decision_mode)
                else:
                    confirmed.pop((event.session_id, event.parent_tool_use_id), None)
                seen.add(block.id)
                pending[block.id] = NativeToolRequest(
                    invocation=block, session_id=event.session_id, parent_tool_use_id=event.parent_tool_use_id
                )
            elif block.type == _TOOL_RESULT_TYPE:
                if (
                    results
                    or event.type != _USER_TYPE
                    or event.message is None
                    or event.message.role != _USER_TYPE
                    or not block.tool_use_id
                ):
                    raise InspectorBoundaryError(_BROKEN_TOOL_CORRELATION)
                request = pending.pop(block.tool_use_id, None)
                if request is None or (request.session_id, request.parent_tool_use_id) != (
                    event.session_id,
                    event.parent_tool_use_id,
                ):
                    raise InspectorBoundaryError(_BROKEN_TOOL_CORRELATION)
                if request.invocation.name == _STRUCTURED_OUTPUT_TOOL_NAME and block.is_error is not True:
                    report = report_model(decision_mode).model_validate(request.invocation.input)
                    confirmed[(request.session_id, request.parent_tool_use_id)] = report
        if event.type == _WRAPPER_TYPE:
            if pending:
                raise InspectorBoundaryError(_BROKEN_TOOL_CORRELATION)
            results.append(event)
    if len(results) != 1:
        raise _ClaudeStreamOutputError(_NO_STRUCTURED_RESULT)
    if pending:
        raise InspectorBoundaryError(_BROKEN_TOOL_CORRELATION)
    result = results[0]
    if result.subtype == _STRUCTURED_SUCCESS and result.is_error is not True and result.structured_output is not None:
        report = report_model(decision_mode).model_validate(result.structured_output)
        if not result.session_id or confirmed.get((result.session_id, result.parent_tool_use_id)) != report:
            raise InspectorBoundaryError(_FORMATTER_REPORT_MISMATCH)
    return result


def _validate_tool_invocation(
    invocation: ClaudeToolUse,
    evidence_directory: Path,
    decision_mode: ReleaseDecisionMode = ReleaseDecisionMode.AUTOMATIC,
) -> None:
    """Keep each logged tool request inside the prepared source tree and tool allowlist."""
    if invocation.name == _STRUCTURED_OUTPUT_TOOL_NAME:
        report_model(decision_mode).model_validate(invocation.input)
        return
    if invocation.name not in _ALLOWED_TOOL_NAMES or invocation.input is None:
        raise InspectorBoundaryError(_UNEXPECTED_TOOL_EVENT)
    file_input = ClaudeFileToolInput.model_validate(invocation.input)
    paths: list[str]
    if invocation.name == _READ_TOOL_NAME:
        if file_input.file_path is None:
            raise InspectorBoundaryError(_UNEXPECTED_TOOL_EVENT)
        paths = [file_input.file_path]
    else:
        path_value = file_input.path
        if path_value is None:
            paths = [_EMPTY]
        elif isinstance(path_value, str):
            paths = [path_value]
        else:
            paths = path_value
    root = evidence_directory.resolve()
    if invocation.name == _GLOB_TOOL_NAME and file_input.pattern is not None:
        pattern_path = PurePosixPath(file_input.pattern)
        if (
            _NULL_BYTE in file_input.pattern
            or any(part == _PARENT_DIRECTORY_PART for part in pattern_path.parts)
            or (
                file_input.pattern.startswith(_GLOB_NEGATION_PREFIX)
                and PurePosixPath(file_input.pattern.removeprefix(_GLOB_NEGATION_PREFIX)).is_absolute()
            )
        ):
            raise InspectorBoundaryError(_UNEXPECTED_TOOL_PATH)
        if pattern_path.is_absolute() and (
            not file_input.pattern.startswith(str(root) + _PATH_SEPARATOR)
            or any(character in str(root) for character in _GLOB_ROOT_METACHARACTERS)
            or any(character in file_input.pattern for character in _AMBIGUOUS_ABSOLUTE_GLOB_CHARACTERS)
            or not Path(file_input.pattern).resolve().is_relative_to(root)
        ):
            raise InspectorBoundaryError(_UNEXPECTED_TOOL_PATH)
    for path_text in paths:
        pure_path = PurePosixPath(path_text)
        if any(part == _PARENT_DIRECTORY_PART for part in pure_path.parts):
            raise InspectorBoundaryError(_UNEXPECTED_TOOL_PATH)
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.resolve().is_relative_to(root):
            raise InspectorBoundaryError(_UNEXPECTED_TOOL_PATH)


def _invalid_report(
    process: IsolatedProcessResult,
    oauth_token: str,
    result_directory: Path,
    private_paths: tuple[Path, ...],
) -> ClaudeInspectionResult:
    """Retain malformed or absent structured output without grading its free text."""
    diagnostic = _write_diagnostic(
        result_directory,
        _CLAUDE_STDOUT_FILENAME,
        _safe_diagnostic(process.stdout, oauth_token, private_paths),
    )
    return _failed_result(
        ProviderFailure.INVALID_REPORT,
        process.return_code,
        False,
        _DIAGNOSTIC_INVALID_REPORT,
        result_directory,
        diagnostic,
    )


def _failed_result(
    failure: ProviderFailure,
    return_code: int | None,
    timed_out: bool,
    message: str,
    result_directory: Path,
    diagnostic_path: str | None = None,
) -> ClaudeInspectionResult:
    """Record one typed Claude failure and safe diagnostic path."""
    if diagnostic_path is None:
        diagnostic_path = _write_diagnostic(
            result_directory,
            _CLAUDE_STDERR_FILENAME,
            message.encode(_CONFIG_ENCODING),
        )
    return ClaudeInspectionResult(
        attempt=ProviderAttempt(
            provider=ProviderName.CLAUDE,
            outcome=ProviderOutcome.FAILED,
            failure=failure,
            report_sha256=None,
            auth_settled=True,
            exit_code=return_code,
            timed_out=timed_out,
            diagnostic_path=diagnostic_path,
        ),
        report=None,
        report_path=None,
    )


def _settings_content(
    evidence_directory: Path,
    controller_directory: Path,
    config_directory: Path,
    principal_home: Path,
    principal_temp: Path,
) -> bytes:
    """Render only explicit native read and deny rules for the isolated session."""
    deny_rules = [
        _read_rule(controller_directory),
        _read_rule(config_directory),
        _read_rule(principal_home),
        _read_rule(principal_temp),
        _read_rule(_PROC_DIRECTORY),
        _read_rule(_RUN_DIRECTORY),
        _read_rule(_SYSTEM_RUN_DIRECTORY),
        _read_rule(Path(_MANAGED_SETTINGS_DIRECTORY)),
    ]
    settings = {
        _PERMISSIONS_KEY: {
            _BLOCK_OUTSIDE_READS_KEY: True,
            _DEFAULT_MODE_KEY: _DONT_ASK_MODE,
            _DENY_KEY: deny_rules,
        }
    }
    return json.dumps(settings, ensure_ascii=_JSON_ENSURE_ASCII, indent=_JSON_INDENT).encode(_CONFIG_ENCODING)


def _read_rule(path: Path) -> str:
    """Return a Claude absolute-path read deny rule."""
    normalized = path.resolve().as_posix().lstrip(_LEADING_SLASH).rstrip(_TRAILING_SLASH)
    return _READ_RULE_PREFIX + normalized + _READ_RULE_SUFFIX


def _safe_diagnostic(content: bytes, oauth_token: str, private_paths: tuple[Path, ...]) -> bytes:
    """Remove the exact subscription token and machine-local runtime paths from diagnostics."""
    text = content.decode(_CONFIG_ENCODING, errors=_BACKSLASH_REPLACE)
    if oauth_token:
        text = text.replace(oauth_token, _REDACTION)
    for path, replacement in zip(private_paths, _PRIVATE_PATH_REPLACEMENTS, strict=True):
        text = text.replace(str(path), replacement)
    return text.encode(_CONFIG_ENCODING)


def _write_report(result_directory: Path, report_bytes: bytes) -> str:
    """Write one validated report under its controller-owned output root."""
    report_directory = result_directory / _REPORT_DIRECTORY
    report_directory.mkdir(mode=_PRIVATE_RESULT_DIRECTORY_MODE, parents=True, exist_ok=True)
    path = report_directory / _CLAUDE_REPORT_FILENAME
    if path.exists() or path.is_symlink():
        raise ValueError(_RESULT_PATH_EXISTS)
    path.write_bytes(report_bytes)
    path.chmod(_PRIVATE_RESULT_FILE_MODE)
    return _REPORT_FILE_PATH


def _write_diagnostic(result_directory: Path, filename: str, content: bytes) -> str:
    """Persist one sanitized CLI diagnostic for the stage artifact."""
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
    return _CLAUDE_DIAGNOSTIC_PATH + filename
