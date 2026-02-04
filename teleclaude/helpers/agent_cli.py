#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""One-shot agent runner with schema-required JSON output."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Anchor imports at repo root for teleclaude constants access.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from typing import cast

from teleclaude.constants import AGENT_METADATA, AgentCliDict
from teleclaude.helpers.agent_types import AgentName, ThinkingMode


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
    if schema_json:
        return json.loads(schema_json)
    if schema_file:
        return json.loads(Path(schema_file).read_text(encoding="utf-8"))
    raise SystemExit("ERROR: schema is required (--schema-json or --schema-file)")


def _pick_agent(preferred: AgentName | None) -> AgentName:
    if preferred:
        return preferred
    for candidate in (AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX):
        if shutil.which(candidate.value):
            return candidate
    raise SystemExit("ERROR: no available agent CLI found (claude/gemini/codex)")


def _run_agent(
    agent: AgentName,
    thinking_mode: ThinkingMode,
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema
    *,
    tools: str | None,
    mcp_tools: str | None,
    debug_raw: bool = False,
    timeout_s: int | None = None,
) -> str:
    metadata = AGENT_METADATA.get(agent.value)
    if not metadata:
        raise RuntimeError(f"Unknown agent '{agent.value}'")

    cli = cast(AgentCliDict, metadata.get("cli", {}))
    base_cmd_raw = cli.get("base_cmd")
    if not base_cmd_raw or not isinstance(base_cmd_raw, list):
        raise RuntimeError(f"Missing cli_base_cmd for agent '{agent.value}'")

    base_cmd: list[str] = []
    for part in base_cmd_raw:
        base_cmd.extend(shlex.split(str(part)))

    exec_subcommand = str(metadata.get("exec_subcommand", "") or "")
    model_flags = cast(dict[str, str], metadata.get("model_flags", {}))
    model_flag = model_flags.get(thinking_mode.value)
    if model_flag is None:
        raise RuntimeError(f"Invalid thinking_mode '{thinking_mode.value}' for agent '{agent.value}'")

    cmd_parts = list(base_cmd)
    if exec_subcommand:
        cmd_parts.append(exec_subcommand)
    if model_flag:
        cmd_parts.extend(shlex.split(str(model_flag)))

    output_format = str(cli.get("output_format", "") or "")
    if output_format:
        cmd_parts.extend(shlex.split(output_format))

    schema_arg = str(cli.get("schema_arg", "") or "")
    schema_file = str(cli.get("schema_file", "") or "")
    prompt_flag = bool(cli.get("prompt_flag", True))

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

    tools_arg = str(cli.get("tools_arg", "") or "")
    if tools_arg and tools is not None:
        cmd_parts.extend([tools_arg, tools])

    mcp_tools_arg = str(cli.get("mcp_tools_arg", "") or "")
    if mcp_tools_arg and mcp_tools is not None:
        cmd_parts.extend([mcp_tools_arg, mcp_tools])

    if prompt_flag:
        cmd_parts.extend(["-p", prompt])
    else:
        cmd_parts.append(prompt)
    if debug_raw:
        print(json.dumps({"debug_cmd": cmd_parts}))
    result = subprocess.run(
        cmd_parts,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Agent CLI failed")
    return result.stdout


def run_once(
    *,
    agent: str | None,
    thinking_mode: str,
    system: str,
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema
    tools: str | None = None,
    mcp_tools: str | None = None,
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
    cli = cast(AgentCliDict, AGENT_METADATA[agent_enum.value].get("cli", {}))
    response_field = str(cli.get("response_field", "") or "")
    response_field_type = str(cli.get("response_field_type", "object") or "object")
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
    parser.add_argument("--prompt", required=True, help="User prompt")
    parser.add_argument("--schema-json", help="JSON schema string (required if no --schema-file)")
    parser.add_argument("--schema-file", help="Path to JSON schema file (required if no --schema-json)")
    args = parser.parse_args()

    try:
        schema = _load_schema(args.schema_json, args.schema_file)
        payload = run_once(
            agent=args.agent,
            thinking_mode=args.thinking_mode,
            system=args.system,
            prompt=args.prompt,
            schema=schema,
            tools=args.tools,
            mcp_tools=args.mcp_tools,
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
