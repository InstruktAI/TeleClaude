#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""One-shot agent runner with schema-required JSON output.

Uses runtime-resolved binaries with lean flags optimized for fast,
toolless, structured-output invocations.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from typing_extensions import TypedDict

# Anchor imports at repo root for teleclaude constants access.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from instrukt_ai_logging import get_logger

from teleclaude.constants import API_SOCKET_PATH
from teleclaude.helpers.agent_types import AgentName, ThinkingMode
from teleclaude.runtime.binaries import resolve_agent_binary

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# One-shot CLI protocol — self-contained, not shared with interactive sessions.
# Uses runtime policy binaries (macOS launchers on macOS, direct binaries elsewhere).
# Flags are trimmed for minimal bootstrap: no tools, no skills, no project config.
# ---------------------------------------------------------------------------


class _OneshotSpec(TypedDict, total=False):
    flags: str
    model_flags: dict[str, str]
    output_format: str
    schema_arg: str
    schema_file: str
    prompt_flag: bool
    response_field: str
    response_field_type: str
    tools_arg: str
    mcp_tools_arg: str
    tools_map: dict[str, str]
    exec_subcommand: str


_AGENT_MODEL_FLAGS: dict[str, dict[str, str]] = {
    "claude": {
        "fast": "--model haiku",
        "med": "--model sonnet",
        "slow": "--model opus",
    },
    "gemini": {
        "fast": "-m gemini-2.5-flash-lite",
        "med": "-m gemini-3-flash-preview",
        "slow": "-m gemini-3-pro-preview",
    },
    "codex": {
        "fast": "-m gpt-5.3-codex-spark --config model_reasoning_effort='medium'",
        "med": "-m gpt-5.3-codex-spark --config model_reasoning_effort='high'",
        "slow": "-m gpt-5.3-codex-spark --config model_reasoning_effort='xhigh'",
    },
}


_ONESHOT_SPEC: dict[str, _OneshotSpec] = {
    "claude": {
        "flags": (
            "--dangerously-skip-permissions --no-session-persistence --no-chrome"
            " --strict-mcp-config"
            ' --tools "" --disable-slash-commands --setting-sources user'
            ' --settings \'{"forceLoginMethod": "claudeai",'
            ' "enabledMcpjsonServers": [], "disableAllHooks": true}\''
        ),
        "model_flags": _AGENT_MODEL_FLAGS["claude"],
        "output_format": "--output-format json",
        "schema_arg": "--json-schema",
        "prompt_flag": True,
        "response_field": "result",
        "response_field_type": "string_json",
        "tools_arg": "--allowed-tools",
        "mcp_tools_arg": "",
        "tools_map": {"web_search": "web_search"},
    },
    "gemini": {
        "flags": "--yolo --allowed-mcp-server-names _none_",
        "model_flags": _AGENT_MODEL_FLAGS["gemini"],
        "output_format": "-o json",
        "schema_arg": "",
        "prompt_flag": True,
        "response_field": "response",
        "response_field_type": "string_json",
        "tools_arg": "--allowed-tools",
        "mcp_tools_arg": "--allowed-mcp-server-names",
        "tools_map": {"web_search": "google_web_search"},
    },
    "codex": {
        "flags": "--dangerously-bypass-approvals-and-sandbox --search",
        "model_flags": _AGENT_MODEL_FLAGS["codex"],
        "exec_subcommand": "exec --ephemeral",
        "output_format": "",
        "schema_arg": "--output-schema",
        "schema_file": "true",
        "prompt_flag": False,
        "response_field": "",
        "response_field_type": "object",
        "tools_arg": "",
        "mcp_tools_arg": "",
        "tools_map": {"web_search": "web_search"},
    },
}


def _extract_json_object(text: str) -> str:
    """Extract JSON object from text that may contain markdown fences or extra output."""
    fence_match = __import__("re").search(r"```(?:json)?\s*\n(.*?)\n```", text, __import__("re").DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    brace_count = 0
    start_idx = -1
    in_string = False
    escape_next = False
    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    return text[start_idx : i + 1]
    return text.strip()


def _load_schema(
    schema_json: str | None, schema_file: str | None
) -> dict[str, object]:  # guard: loose-dict - JSON schema is an arbitrary nested structure
    text = ""
    if schema_json:
        text = schema_json
    elif schema_file:
        text = Path(schema_file).read_text(encoding="utf-8")
    else:
        raise ValueError("ERROR: schema is required (--schema-json or --schema-file)")

    return json.loads(_extract_json_object(text))


def _pick_agent(preferred: AgentName | None) -> AgentName:
    def binary_available(agent: AgentName) -> bool:
        binary = resolve_agent_binary(agent.value)
        if "/" in binary:
            path = Path(binary).expanduser()
            return path.exists() and path.is_file() and os.access(path, os.X_OK)
        return shutil.which(binary) is not None

    def db_available(agent: AgentName) -> bool:
        """Read agent availability from teleclaude.db.

        Missing DB/table/row is treated as available to preserve standalone behavior.
        """
        db_path = _REPO_ROOT / "teleclaude.db"
        if not db_path.exists():
            return True

        try:
            with sqlite3.connect(str(db_path), timeout=0.2) as conn:
                row = conn.execute(
                    "SELECT available, unavailable_until, reason FROM agent_availability WHERE agent = ?",
                    (agent.value,),
                ).fetchone()
        except sqlite3.Error:
            return True

        if row is None:
            return True

        available_raw, unavailable_until, reason = row
        if isinstance(reason, str) and reason.startswith("degraded"):
            return False
        if bool(available_raw):
            return True

        # Expired temporary unavailability should not block selection.
        if isinstance(unavailable_until, str) and unavailable_until.strip():
            parsed = _parse_iso_utc(unavailable_until)
            if parsed is not None and parsed <= datetime.now(timezone.utc):
                return True

        return False

    def agent_usable(agent: AgentName) -> bool:
        return binary_available(agent) and db_available(agent)

    if preferred:
        if not binary_available(preferred):
            raise SystemExit(f"ERROR: configured binary for {preferred.value} is not available")
        if not db_available(preferred):
            raise SystemExit(f"ERROR: configured agent {preferred.value} is marked unavailable or degraded")
        return preferred
    for candidate in (AgentName.CLAUDE, AgentName.CODEX, AgentName.GEMINI):
        if agent_usable(candidate):
            return candidate
    raise SystemExit("ERROR: no available agent CLI found for runtime policy")


def _parse_iso_utc(value: str) -> datetime | None:
    """Parse ISO timestamp to timezone-aware UTC datetime."""
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# CLI agents authenticate via OAuth/account allowance, not API keys.
# Each CLI reads credentials from its own store after user login:
#   Claude  → macOS Keychain  (service "Claude Code-credentials")
#   Codex   → ~/.codex/auth.json  (OAuth2 JWTs from ChatGPT account)
#   Gemini  → ~/.gemini/oauth_creds.json  (Google OAuth2, selectedType "oauth-personal")
#
# API keys are reserved for SDK operations (summarization, voice) that
# need speed. Leaking them to CLI subprocesses would bypass OAuth and
# incur direct API charges.
_CLI_STRIP_PREFIXES = ("CLAUDE_CODE", "CLAUDECODE")
_CLI_STRIP_EXACT = {
    "ANTHROPIC_API_KEY",  # Claude: bypasses OAuth, uses direct API billing
    "ANTHROPIC_AUTH_TOKEN",  # Claude: alternative auth token
    "OPENAI_API_KEY",  # Codex: bypasses ChatGPT OAuth
    "GEMINI_API_KEY",  # Gemini: bypasses Google OAuth
    "GOOGLE_API_KEY",  # Gemini: bypasses Google OAuth (Vertex express)
}


def _cli_env() -> dict[str, str]:
    """Build a clean environment for CLI agent subprocesses."""
    return {
        k: v
        for k, v in os.environ.items()
        if k not in _CLI_STRIP_EXACT and not any(k.startswith(p) for p in _CLI_STRIP_PREFIXES)
    }


def _run_agent(
    agent: AgentName,
    thinking_mode: ThinkingMode,
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema
    *,
    tools: str | None,
    mcp_tools: str | None,
    input_mode: Literal["stdin", "arg"] = "stdin",
    debug_raw: bool = False,
    timeout_s: int | None = None,
) -> str:
    spec = _ONESHOT_SPEC.get(agent.value)
    if not spec:
        raise RuntimeError(f"Unknown agent '{agent.value}'")

    binary = resolve_agent_binary(agent.value)
    flags = str(spec.get("flags", ""))
    model_flags = spec.get("model_flags", {})
    model_flag = model_flags.get(thinking_mode.value)
    if model_flag is None:
        raise RuntimeError(f"Invalid thinking_mode '{thinking_mode.value}' for agent '{agent.value}'")

    # Assemble command: binary + flags + exec_subcommand + model
    cmd_parts = shlex.split(f"{binary} {flags}".strip())

    exec_subcommand = str(spec.get("exec_subcommand", "") or "")
    if exec_subcommand:
        cmd_parts.extend(shlex.split(exec_subcommand))
    if model_flag:
        cmd_parts.extend(shlex.split(str(model_flag)))

    output_format = str(spec.get("output_format", "") or "")
    if output_format:
        cmd_parts.extend(shlex.split(output_format))

    schema_arg = str(spec.get("schema_arg", "") or "")
    schema_file = str(spec.get("schema_file", "") or "")
    prompt_flag = bool(spec.get("prompt_flag", True))

    if schema_arg:
        if schema_file.lower() == "true":
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(schema, f)
                schema_path = f.name
            cmd_parts.extend([schema_arg, schema_path])
        else:
            cmd_parts.extend([schema_arg, json.dumps(schema)])
    else:
        prompt = f"{prompt}\n\nExpected JSON schema:\n{json.dumps(schema)}"

    tools_arg = str(spec.get("tools_arg", "") or "")
    if tools_arg and tools is not None:
        cmd_parts.extend([tools_arg, tools])

    mcp_tools_arg = str(spec.get("mcp_tools_arg", "") or "")
    if mcp_tools_arg and mcp_tools is not None:
        cmd_parts.extend([mcp_tools_arg, mcp_tools])

    # Handle prompt passing based on input_mode
    use_stdin = input_mode == "stdin"

    if agent == AgentName.CLAUDE:
        if use_stdin:
            if prompt_flag:
                cmd_parts.append("-p")
        else:
            if prompt_flag:
                cmd_parts.extend(["-p", prompt])
            else:
                cmd_parts.append(prompt)

    elif agent == AgentName.CODEX:
        # Codex reads stdin if no prompt arg.
        if not use_stdin:
            cmd_parts.append(prompt)

    elif agent == AgentName.GEMINI:
        # Gemini reads stdin natively; -p "" makes it ignore stdin.
        # Only pass -p when using arg mode with actual content.
        if not use_stdin:
            if prompt_flag:
                cmd_parts.extend(["-p", prompt])
            else:
                cmd_parts.append(prompt)

    if debug_raw:
        print(json.dumps({"debug_cmd": cmd_parts, "prompt_len": len(prompt)}))

    env = _cli_env()

    result = subprocess.run(
        cmd_parts,
        input=prompt if use_stdin else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_s,
        env=env,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()[:200] or "Agent CLI failed"
        raise RuntimeError(detail)
    return result.stdout


# ---------------------------------------------------------------------------
# Job invocation — full interactive subprocess with tools and MCP enabled.
# Unlike run_once (lobotomized JSON), run_job gives the agent full access.
# ---------------------------------------------------------------------------

_JOB_SPEC: dict[str, dict[str, str | dict[str, str]]] = {
    "claude": {
        "flags": (
            "--dangerously-skip-permissions --no-session-persistence --no-chrome"
            " --disable-slash-commands --setting-sources user"
            ' --settings \'{"forceLoginMethod": "claudeai", "disableAllHooks": true}\''
        ),
        "model_flags": _AGENT_MODEL_FLAGS["claude"],
    },
    "gemini": {
        "flags": "--yolo",
        "model_flags": _AGENT_MODEL_FLAGS["gemini"],
    },
    "codex": {
        "flags": "--dangerously-bypass-approvals-and-sandbox",
        "model_flags": _AGENT_MODEL_FLAGS["codex"],
        "exec_subcommand": "exec",
    },
}


def run_job(
    *,
    agent: str | None,
    thinking_mode: str,
    prompt: str,
    role: str = "admin",
    timeout_s: int | None = None,
    metadata: dict[str, str] | None = None,
) -> int:
    """Spawn a full interactive agent subprocess for a cron job.

    Unlike run_once, the agent has full tool access (bash, read, write, etc.)
    and MCP access when the daemon is running. Returns the subprocess exit code.
    """
    try:
        # Check if daemon is running by attempting to connect to MCP socket
        if not os.path.exists("/tmp/teleclaude.sock"):
            logger.warning("Daemon socket not found, falling back to standalone agent process")
            raise ConnectionError("Daemon unavailable")

        # Daemon is running - use API to start session
        from teleclaude.cli.api_client import TelecAPIClient

        # Run async API call in sync context
        async def _start_session_via_api() -> None:  # pyright: ignore[reportUnusedFunction]
            client = TelecAPIClient(API_SOCKET_PATH)
            await client.connect()
            try:
                # Create session with explicit job metadata
                result = await client.create_session(
                    computer="local",  # Cron runs locally
                    project_path=os.getcwd(),  # Current working dir of runner
                    agent=agent or "claude",
                    thinking_mode=thinking_mode,
                    title=f"Job: {metadata.get('job_name', 'unknown') if metadata else 'unknown'}",
                    message=prompt,
                    human_role=role,
                    metadata=metadata,
                )
                logger.info("Started agent job session via API: %s", result.session_id)
                # We don't wait for completion here in the API client model yet
                # Ideally we'd tail it or wait for a signal, but for now we just start it.
                # The runner expects blocking behavior though...
                # This reveals a mismatch: run_job expects to BLOCK until done.
                # The previous implementation spawned a subprocess.
                # We should stick to subprocess for now but PASS METADATA via ENV VARS
                # so the agent process (which connects to daemon) can register itself correctly.
            finally:
                await client.close()

        import asyncio

        asyncio.run(_start_session_via_api())
        return 0

    except Exception:
        # Fallback or standard path: spawn subprocess
        pass

    agent_enum = _pick_agent(AgentName.from_str(agent) if agent else None)
    mode_enum = ThinkingMode.from_str(thinking_mode or ThinkingMode.FAST.value)

    spec = _JOB_SPEC.get(agent_enum.value)
    if not spec:
        raise RuntimeError(f"No job spec for agent '{agent_enum.value}'")

    binary = resolve_agent_binary(agent_enum.value)
    flags = str(spec.get("flags", ""))
    model_flags_raw = spec.get("model_flags", {})
    model_flags: dict[str, str] = model_flags_raw if isinstance(model_flags_raw, dict) else {}
    model_flag = model_flags.get(mode_enum.value)
    if model_flag is None:
        raise RuntimeError(f"Invalid thinking_mode '{mode_enum.value}' for agent '{agent_enum.value}'")

    cmd_parts = shlex.split(f"{binary} {flags}".strip())

    exec_subcommand = str(spec.get("exec_subcommand", "") or "")
    if exec_subcommand:
        cmd_parts.extend(shlex.split(exec_subcommand))
    if model_flag:
        cmd_parts.extend(shlex.split(model_flag))

    cmd_parts.extend(["-p", prompt])

    env = _cli_env()
    env["TELECLAUDE_JOB_ROLE"] = role

    # Inject metadata as environment variables for the agent process to pick up
    # The agent wrapper/bootstrap needs to read these and pass them to session creation
    if metadata:
        env["TELECLAUDE_JOB_METADATA"] = json.dumps(metadata)

    result = subprocess.run(
        cmd_parts,
        capture_output=False,
        text=True,
        check=False,
        timeout=timeout_s,
        env=env,
    )
    return result.returncode


def run_once(
    *,
    agent: str | None,
    thinking_mode: str,
    system: str,
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema
    tools: str | None = None,
    mcp_tools: str | None = None,
    input_mode: Literal["stdin", "arg"] = "stdin",
    debug_raw: bool = False,
    timeout_s: int | None = None,
) -> dict[str, object]:  # guard: loose-dict - Agent response with embedded result
    agent_enum = _pick_agent(AgentName.from_str(agent) if agent else None)
    mode_enum = ThinkingMode.from_str(thinking_mode or ThinkingMode.FAST.value)

    schema_blob = json.dumps(schema)
    system_prefix = f"system: {system}\n\n" if system.strip() else ""
    combined_prompt = (
        f"{system_prefix}user: {prompt}\n\nReturn ONLY valid JSON that matches this schema:\n{schema_blob}"
    )

    raw = _run_agent(
        agent_enum,
        mode_enum,
        combined_prompt,
        schema,
        tools=tools,
        mcp_tools=mcp_tools,
        input_mode=input_mode,
        debug_raw=debug_raw,
        timeout_s=timeout_s,
    )
    if debug_raw:
        print(json.dumps({"debug_raw": raw}))
    json_text = _extract_json_object(raw)
    parsed = json.loads(json_text)
    if debug_raw:
        print(
            json.dumps(
                {
                    "debug_payload_fields": {
                        "has_result": isinstance(parsed, dict) and "result" in parsed,
                        "has_structured_output": isinstance(parsed, dict) and "structured_output" in parsed,
                        "has_tool_use": bool(
                            isinstance(parsed, dict) and parsed.get("usage", {}).get("server_tool_use")
                        ),
                    }
                }
            )
        )
    spec = _ONESHOT_SPEC[agent_enum.value]
    response_field = str(spec.get("response_field", "") or "")
    response_field_type = str(spec.get("response_field_type", "object") or "object")
    if isinstance(parsed, dict) and "structured_output" in parsed:
        extracted = parsed["structured_output"]
        if not isinstance(extracted, dict):
            raise RuntimeError("Agent structured_output is not a JSON object")
        parsed = extracted
    elif response_field:
        if not (isinstance(parsed, dict) and response_field in parsed):
            raise RuntimeError("Agent response missing configured response_field")
        extracted = parsed[response_field]
        if response_field_type == "string_json":
            if not isinstance(extracted, str):
                raise RuntimeError("Agent response_field is not a JSON string")
            extracted_json = json.loads(_extract_json_object(extracted))
            if not isinstance(extracted_json, dict):
                raise RuntimeError("Agent response_field did not contain JSON object")
            parsed = extracted_json
        elif response_field_type == "object":
            if not isinstance(extracted, dict):
                raise RuntimeError("Agent response_field is not a JSON object")
            parsed = extracted
        else:
            raise RuntimeError(f"Unknown response_field_type '{response_field_type}'")
    elif not isinstance(parsed, dict):
        raise RuntimeError("Agent returned non-JSON object")
    return {
        "status": "ok",
        "agent": agent_enum.value,
        "thinking_mode": mode_enum.value,
        "raw": raw,
        "result": parsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot agent runner (JSON output required).")
    parser.add_argument("--agent", choices=AgentName.choices(), help="Agent name (optional)")
    parser.add_argument("--thinking-mode", choices=ThinkingMode.choices(), default="fast")
    parser.add_argument("--system", default="You are a helpful assistant.", help="System prompt")
    parser.add_argument(
        "--tools",
        help='Tools list. "" disables tools. Omit to allow all.',
    )
    parser.add_argument(
        "--mcp-tools",
        help='MCP tools list. "" disables. Omit to allow all.',
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="User prompt string")
    group.add_argument("--prompt-file", help="Path to file containing user prompt")

    parser.add_argument("--schema-json", help="JSON schema string (required if no --schema-file)")
    parser.add_argument("--schema-file", help="Path to JSON schema file (required if no --schema-file)")
    args = parser.parse_args()

    try:
        input_mode: Literal["stdin", "arg"] = "arg"
        if args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
            input_mode = "stdin"
        else:
            prompt = args.prompt
            input_mode = "arg"

        schema = _load_schema(args.schema_json, args.schema_file)
        payload = run_once(
            agent=args.agent,
            thinking_mode=args.thinking_mode,
            system=args.system,
            prompt=prompt,
            schema=schema,
            tools=args.tools,
            mcp_tools=args.mcp_tools,
            input_mode=input_mode,
        )
        print(json.dumps(payload))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI error path
        payload = {
            "status": "error",
            "agent": args.agent if args.agent else None,
            "thinking_mode": args.thinking_mode if args.thinking_mode else None,
            "error": str(exc),
        }
        print(json.dumps(payload))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
