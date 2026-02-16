"""Integration tests for agent CLI invocation matrix.

Two-tier architecture:
  Tier 1 (Transport): No tools, no MCP, no hooks, no sessions.
                       Proves CLI plumbing works as a black box.
  Tier 2 (Permission): Role-specific tool configs.
                        Proves enforcement per Admin/Member/Stranger.

Dogfood: uses our own release-report-schema.md as the test payload
so we always exercise realistic structured output.
"""

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


def run_cli(
    agent: str,
    *,
    prompt: str | None = None,
    prompt_file: Path | None = None,
    schema_file: Path | None = None,
    schema_json: str | None = None,
    timeout: int = 15,
) -> dict:
    """Invoke agent CLI and return parsed JSON."""
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


def _assert_valid_report(payload: dict, agent: str) -> None:
    """Assert payload matches release-report-schema structure."""
    assert payload["status"] == "ok", f"{agent} failed: {payload.get('error')}"
    result = payload["result"]
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

    @pytest.mark.timeout(20)
    def test_inline_arg(self, agent):
        """Prompt as CLI argument returns valid dogfood JSON."""
        payload = run_cli(agent, prompt=TRANSPORT_PROMPT, schema_file=SCHEMA_FILE)
        _assert_valid_report(payload, agent)

    @pytest.mark.timeout(20)
    def test_stdin_pipe(self, agent, tmp_path):
        """Prompt piped via stdin returns valid dogfood JSON."""
        pf = tmp_path / "prompt.txt"
        pf.write_text(TRANSPORT_PROMPT, encoding="utf-8")
        payload = run_cli(agent, prompt_file=pf, schema_file=SCHEMA_FILE)
        _assert_valid_report(payload, agent)

    @pytest.mark.timeout(45)
    def test_large_payload_stdin(self, agent, tmp_path):
        """100KB payload via stdin doesn't hit ARG_MAX."""
        filler = "x" * 100_000
        content = f"Ignore padding: {filler}\n\n{TRANSPORT_PROMPT}"
        pf = tmp_path / "large.txt"
        pf.write_text(content, encoding="utf-8")
        payload = run_cli(agent, prompt_file=pf, schema_file=SCHEMA_FILE, timeout=30)
        _assert_valid_report(payload, agent)


# ---------------------------------------------------------------------------
# Tier 2 — Permission enforcement
#
# Permission model:
#   Admin    — full tool + MCP access
#   Member   — personal folder only, get_context MCP only
#   Stranger — help-desk jail, get_context + shared docs only, sandboxed
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Tier 2: requires daemon + MCP config")
@pytest.mark.parametrize("agent", AGENTS)
class TestPermissionAdmin:
    """Admin role: full access to tools and MCP."""

    def test_full_tool_access(self, agent):
        pass

    def test_full_mcp_access(self, agent):
        pass


@pytest.mark.skip(reason="Tier 2: requires daemon + MCP config")
@pytest.mark.parametrize("agent", AGENTS)
class TestPermissionMember:
    """Member role: personal folder + get_context MCP only."""

    def test_get_context_available(self, agent):
        pass

    def test_other_mcp_denied(self, agent):
        pass

    def test_personal_folder_scope(self, agent):
        pass


@pytest.mark.skip(reason="Tier 2: requires daemon + MCP config")
@pytest.mark.parametrize("agent", AGENTS)
class TestPermissionStranger:
    """Stranger role: help-desk + get_context + shared docs only."""

    def test_get_context_available(self, agent):
        pass

    def test_tool_access_denied(self, agent):
        pass

    def test_shared_docs_only(self, agent):
        pass
