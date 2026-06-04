"""Shared command assembly helpers for agent CLI invocations."""

from __future__ import annotations

import shlex


def build_agent_command_parts(
    *,
    binary: str,
    flags: str,
    exec_subcommand: str = "",
    model_flag: str = "",
    output_format: str = "",
) -> list[str]:
    cmd_parts = shlex.split(f"{binary} {flags}".strip())

    for segment in (exec_subcommand, model_flag, output_format):
        if segment:
            cmd_parts.extend(shlex.split(segment))

    return cmd_parts


def with_tool_authorization(cmd_parts: list[str], *, tools_arg: str, tools: str | None) -> list[str]:
    if tools_arg and tools is not None:
        return [*cmd_parts, tools_arg, tools]
    return cmd_parts
