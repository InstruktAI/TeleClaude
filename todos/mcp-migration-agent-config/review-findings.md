# Review Findings: mcp-migration-agent-config

REVIEW COMPLETE: mcp-migration-agent-config

Critical:

- `teleclaude/install/install_hooks.py:499` `_remove_codex_mcp_config()` can delete unrelated Codex config sections. The regex body matcher (`(?:^(?!\[).*$\n?)*`) only stops when the next line starts with `[` at column 1, but TOML allows indented table headers. With input like:
  `model = "x"\n\n[mcp_servers.teleclaude]\n...\n  [other]\nkey = 1\n`
  the function removes both the TeleClaude block and the indented `[other]` section, causing silent data loss in user config. This violates config-preservation expectations in `configure_codex()`. Fix by stopping at `^\s*\[` boundaries (or parser-based editing) and preserve non-target sections.

Important:

- `tests/unit/test_install_hooks.py:343` does not cover the indented-next-section case, so the destructive scrub bug above is undetected. Add a regression test where `[mcp_servers.teleclaude]` is followed by an indented unrelated section and assert the unrelated section remains.
- Manual interactive verification was not executed in this review environment for success criteria that mention live Claude/Gemini/Codex session startup and tool visibility. Unit coverage is strong, but reviewer-observed end-to-end evidence for those interactive checks is still missing.

Suggestions:

- Replace regex-based TOML block removal with parsed TOML mutation to avoid future formatting/whitespace edge cases and reduce risk of config corruption.

## Paradigm-Fit Assessment

- Data flow: Pass. Changes stay in established config/agent command paths; no bypass of core data layers.
- Component reuse: Pass. Existing `configure_codex()` flow is reused; no duplicate installer path introduced.
- Pattern consistency: Pass with one exception: regex-based config surgery is brittle versus parser-safe mutation patterns used elsewhere.

## Manual Verification Evidence

- Reviewer executed targeted tests:
  - `pytest -q tests/unit/test_agent_cli.py tests/unit/test_install_hooks.py` (27 passed)
  - `pytest -q tests/unit/test_api_auth.py::test_require_clearance_denies_excluded_tool tests/unit/test_api_auth.py::test_verify_caller_rejects_tmux_mismatch tests/unit/test_context_selector.py::test_non_admin_sees_only_public_visibility tests/unit/test_daemon_independent_jobs.py::test_run_agent_job_creates_session_via_api tests/unit/test_tmux_bridge_tmpdir.py::test_create_tmux_session_injects_per_session_tmpdir` (5 passed)
- Reviewer reproduction for critical bug was executed directly in Python by calling `_remove_codex_mcp_config()` with concrete TOML content.
- Reviewer did not run live interactive agent sessions in this environment.

## Fixes Applied

- Critical: `_remove_codex_mcp_config()` removed indented non-target TOML sections.
  Fix: Updated section-removal regex to line-based matching that stops at any next table header (`^[ \\t]*\\[`), and aligned the deprecated `ensure_codex_mcp_config()` matcher to the same boundary semantics.
  Commit: `2abd16cf`
- Important: missing regression coverage for indented-next-section case.
  Fix: Added `test_configure_codex_preserves_indented_section_after_mcp_block` to assert `[other]` survives TeleClaude MCP section removal.
  Commit: `2abd16cf`
- Important: missing manual interactive evidence for Claude/Gemini/Codex session startup and tool visibility.
  Fix attempt: Ran `telec sessions start --computer local --project /Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-agent-config --agent {claude|gemini|codex} --mode fast --message "Reply only with OK"`.
  Result: blocked by environment policy (`Error: permission denied — role 'worker' is not permitted to call teleclaude__start_session`), so interactive evidence could not be generated from this worker role.
  Commit: `N/A (blocked by worker-role permissions)`

Verdict: REQUEST CHANGES
