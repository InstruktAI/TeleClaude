"""Integration tests for agent CLI invocation matrix.

Tier 1 (Transport): No tools, no MCP, no hooks, no sessions.
                     Proves CLI plumbing works as a black box.

Dogfood: uses our own release-report-schema.md as the test payload
so we always exercise realistic structured output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.expensive

WRAPPER_CMD = [sys.executable, "-m", "teleclaude.helpers.agent_cli"]
SCHEMA_FILE = Path("docs/project/spec/release-report-schema.md")

AGENTS = ["claude", "codex", "gemini"]

# Deterministic dogfood prompt — agents just fill in the schema fields.
TRANSPORT_PROMPT = (
    "Classify this change as 'none'. "
    "Rationale: 'Transport test — no real diff.' "
    "contract_changes: empty array. "
    "release_notes: 'N/A — transport verification only.'"
)


def _agent_enabled(agent: str) -> bool:
    """Check if an agent is enabled in config."""
    try:
        from teleclaude.config import config

        cfg = config.agents.get(agent)
        return cfg is None or cfg.enabled
    except Exception:
        return True  # Assume enabled if config unavailable


def run_cli(
    agent: str,
    *,
    prompt: str | None = None,
    prompt_file: Path | None = None,
    schema_file: Path | None = None,
    schema_json: str | None = None,
    timeout: int = 60,
) -> dict[str, object]:  # guard: loose-dict - CLI JSON output is untyped
    """Invoke agent CLI and return parsed JSON."""
    if not _agent_enabled(agent):
        pytest.skip(f"agent {agent} is disabled in config")

    cmd = list(WRAPPER_CMD)
    cmd.extend(["--agent", agent, "--thinking-mode", "fast"])

    if prompt:
        cmd.extend(["--prompt", prompt])
    elif prompt_file:
        cmd.extend(["--prompt-file", str(prompt_file)])

    if schema_file:
        cmd.extend(["--schema-file", str(schema_file)])
    elif schema_json:
        cmd.extend(["--schema-json", schema_json])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{agent} subprocess timed out after {timeout}s")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"CLI non-JSON (exit {result.returncode}).\nstdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )

    if payload.get("status") == "error":
        pytest.fail(
            f"CLI error: {payload.get('error')}\n"
            f"agent={agent} returncode={result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )

    return payload


def _assert_valid_report(
    payload: dict[str, object],  # guard: loose-dict - CLI JSON output is untyped
    agent: str,
) -> None:
    """Assert payload matches release-report-schema structure."""
    assert payload["status"] == "ok", f"{agent} failed: {payload.get('error')}"
    result = payload["result"]
    assert isinstance(result, dict)
    assert result["classification"] in ("patch", "minor", "none")
    assert isinstance(result["rationale"], str) and len(result["rationale"]) > 0
    assert isinstance(result["contract_changes"], list)
    assert isinstance(result["release_notes"], str) and len(result["release_notes"]) > 0


# ---------------------------------------------------------------------------
# Tier 1 — Transport: bare invocation, no tools/MCP/sessions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", AGENTS)
class TestTransport:
    """CLI plumbing for all agents without tools or MCP."""

    @pytest.mark.timeout(90)
    def test_inline_arg(self, agent: str) -> None:
        """Prompt as CLI argument returns valid dogfood JSON."""
        payload = run_cli(agent, prompt=TRANSPORT_PROMPT, schema_file=SCHEMA_FILE)
        _assert_valid_report(payload, agent)

    @pytest.mark.timeout(90)
    def test_stdin_pipe(self, agent: str, tmp_path: Path) -> None:
        """Prompt piped via stdin returns valid dogfood JSON."""
        pf = tmp_path / "prompt.txt"
        pf.write_text(TRANSPORT_PROMPT, encoding="utf-8")
        payload = run_cli(agent, prompt_file=pf, schema_file=SCHEMA_FILE)
        _assert_valid_report(payload, agent)

    @pytest.mark.timeout(120)
    def test_large_payload_stdin(self, agent: str, tmp_path: Path) -> None:
        """100KB payload via stdin doesn't hit ARG_MAX."""
        filler = "x" * 100_000
        content = f"Ignore padding: {filler}\n\n{TRANSPORT_PROMPT}"
        pf = tmp_path / "large.txt"
        pf.write_text(content, encoding="utf-8")
        payload = run_cli(agent, prompt_file=pf, schema_file=SCHEMA_FILE, timeout=90)
        _assert_valid_report(payload, agent)
