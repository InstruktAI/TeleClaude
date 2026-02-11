# Context-Aware Checkpoint (Phase 2) — Implementation Plan

## Approach

Two signal axes feed a shared checkpoint builder:

1. **File-based** — `git diff --name-only HEAD` → file category patterns → action instructions
2. **Transcript-based** — transcript JSONL/JSON → tool call timeline → suppression + observations

Both axes merge in a shared builder used by both delivery paths (hook for Claude/Gemini, tmux injection for Codex). No LLM calls. No pytest execution. All heuristics are deterministic pattern matching.

## Files to Change

| File                                                    | Change                                                                                                                  |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `teleclaude/utils/transcript.py`                        | New Layer 2 extraction: `extract_tool_calls_current_turn()`, tail-read I/O, `TurnTimeline`/`ToolCallRecord` dataclasses |
| `teleclaude/constants.py`                               | File category patterns, evidence patterns, heuristic configuration                                                      |
| `teleclaude/hooks/checkpoint.py` (NEW)                  | Shared checkpoint builder, heuristic engine, message composition — thin consumer of transcript.py                       |
| `teleclaude/hooks/receiver.py`                          | Use shared builder; pass transcript path and session context                                                            |
| `teleclaude/core/agent_coordinator.py`                  | Use shared builder for codex tmux injection                                                                             |
| `tests/unit/test_transcript_extraction.py` (NEW)        | Tool-call extraction tests: per-agent formats, turn scoping, bounded read, edge cases                                   |
| `tests/unit/test_checkpoint_builder.py` (NEW)           | Heuristic engine, file categorization, message composition, suppression tests                                           |
| `tests/unit/test_checkpoint_hook.py`                    | Hook route integration tests (adjust existing + add suppression tests)                                                  |
| `tests/unit/test_agent_coordinator.py`                  | Codex route parity tests                                                                                                |
| `docs/project/design/architecture/checkpoint-system.md` | Phase 2 context-aware flow, heuristic engine, two-axis signal model                                                     |

## Task Sequence

### Phase A: Infrastructure

#### Task 1: File category patterns and evidence configuration [x]

Add to `teleclaude/constants.py`:

- File category patterns as a data structure: list of named tuples with (category_name, include_patterns, exclude_patterns, instruction_template, evidence_pattern)
  - `evidence_pattern`: substring(s) to search for in Bash tool call commands that prove the action was already taken
- Daemon bucket: `teleclaude/**/*.py` excluding `teleclaude/hooks/**` and `teleclaude/cli/tui/**`
- Hook runtime bucket: `teleclaude/hooks/**` (no action — auto-applies)
- TUI bucket: `teleclaude/cli/tui/**` → SIGUSR2 reload, evidence: `pkill -SIGUSR2` or `kill -USR2`
- Telec setup bucket: project_setup, templates, pre-commit config, gitattributes, husky → `telec init`, evidence: `telec init`
- Agent artifacts bucket: `agents/**`, `.agents/**`, `**/AGENTS.master.md` → agent-restart, evidence: `agent-restart`
- Config bucket: `config.yml` → `make restart`, evidence: `make restart`
- Dependencies bucket: `pyproject.toml`, `requirements*.txt` → `pip install -e .`, evidence: `pip install`
- Tests-only bucket: `tests/**/*.py` (only when no source changes match)
- Error detection patterns: list of (regex_pattern, feedback_string) for transcript scanning
- Evidence match mode: substring (not regex) for speed and simplicity

**Verify:** Import succeeds, pattern data structure is well-typed.

#### Task 2: Tool-call extraction layer in transcript.py [x]

Extend `teleclaude/utils/transcript.py` with a new Layer 2 consumer alongside the existing rendering and extraction functions. All new code lives IN transcript.py, sharing the existing Layer 0 (I/O) and Layer 1 (format normalization) infrastructure.

**New dataclasses** (in `transcript.py`):

- `ToolCallRecord` dataclass:
  - `tool_name: str` — e.g., "Bash", "Read", "Edit", "Write"
  - `input_data: dict` — tool input parameters (command, file_path, etc.)
  - `had_error: bool` — True if corresponding tool_result has `is_error: true`. This is the structural gate for error state detection — only records with `had_error=True` are candidates for error observations.
  - `result_snippet: str` — first 500 chars of tool result content. Only used for error enrichment when `had_error=True`. For successful tool calls, the snippet is stored but never pattern-matched for error detection.
  - `timestamp: Optional[datetime]`
- `TurnTimeline` dataclass:
  - `tool_calls: list[ToolCallRecord]` — ordered by timestamp
  - `has_data: bool` — False if transcript unavailable or unparseable

**New public function** (in `transcript.py`):

- `extract_tool_calls_current_turn(transcript_path: str, agent_name: AgentName) -> TurnTimeline`
  - Uses `_get_entries_for_agent()` (existing Layer 1) to get normalized entries
  - Walks entries backward from end until a user-role message → turn boundary (same pattern as `render_agent_output()` when no `since_timestamp` is given)
  - Walks forward from boundary, processing `tool_use` and `tool_result` content blocks into `ToolCallRecord` instances
  - Returns `TurnTimeline` with ordered records
  - Returns `TurnTimeline(tool_calls=[], has_data=False)` on any failure

**Layer 0 enhancement — bounded read for JSONL:**

- Add `_iter_jsonl_entries_tail(path: Path, max_bytes: int = 524288) -> Iterable[dict]`
  - Seeks to `file_size - max_bytes`, reads from there
  - Skips the first partial line (since we may land mid-line)
  - Yields entries same as `_iter_jsonl_entries()`
  - Falls back to full read if file is smaller than max_bytes
- Wire `extract_tool_calls_current_turn()` to use the tail reader for JSONL transcripts
- Existing rendering functions are NOT changed — they continue to use the full reader (they already have their own `tail_chars` limiting)

**Block processing:**

The extraction walks `content` blocks the same way `_process_list_content()` does, but instead of appending to a `lines` list, it builds `ToolCallRecord` instances. This is a parallel consumer of the same block structure, not a refactor of the existing renderer. Both share Layer 0 and Layer 1; they diverge at Layer 2.

Tool-use/tool-result pairing: walk content blocks sequentially. When a `tool_use` block is found, create a record. When the next `tool_result` block is found, attach `is_error` and `result_snippet` to the preceding record. This mirrors how the renderer pairs them in `_process_list_content()`.

**Verify:** `tests/unit/test_transcript_extraction.py` — fixture JSONL/JSON files covering Claude, Gemini, and Codex formats. Tests verify:

- Correct tool call extraction from each format
- Turn boundary detection (entries before last user message excluded)
- Bounded read for large JSONL files
- Graceful failure on missing/corrupt transcripts
- Tool-use/tool-result pairing produces correct `had_error` and `result_snippet`

#### Task 3: Heuristic engine [x]

Add to `teleclaude/hooks/checkpoint.py` — this module is a thin consumer of `transcript.py`. It imports `TurnTimeline` and `ToolCallRecord` from transcript.py and never reads or parses transcript files directly.

- `run_heuristics(git_files: list[str], timeline: TurnTimeline, context: CheckpointContext) -> CheckpointResult`
- `CheckpointContext` dataclass:
  - `project_path: str` — for working slug file access
  - `working_slug: Optional[str]` — from session DB
  - `agent_name: AgentName` — for any agent-specific behavior
- `CheckpointResult` dataclass:
  - `categories: list[str]` — matched file categories
  - `required_actions: list[str]` — unsuppressed action instructions, in precedence order
  - `observations: list[str]` — transcript-derived findings
  - `is_all_clear: bool` — True when everything expected was already done

The engine runs these checks in order:

1. **File categorization** — map git_files to categories and instructions (R2)
2. **Verification gap detection** — for each instruction, search timeline for evidence; suppress if found (R4)
3. **Error state detection (two-layer)** — Layer 1: find `is_error: true` tool results, check for resolution evidence (subsequent Bash/Edit/Write targeting same area, or same command re-invoked). Layer 2: for unresolved errors only, pattern-match content to produce enriched feedback (R5)
4. **Edit hygiene** — check Edit tool calls vs Read tool calls (R6)
5. **Working slug alignment** — compare expected vs actual changed files (R7)

Each check is a private function that appends to the result's actions or observations lists. No formal plugin/registry system — just functions called in sequence. Keep it simple.

Resolution evidence for error state detection accepts three signal types:

- Bash tool call with substring match on same filename/module in command
- Edit/Write tool call targeting the same file path
- Re-invocation of the same command (e.g., second `pytest` after a failed first `pytest`)

**Verify:** Unit tests covering each heuristic independently and in combination.

### Phase B: Integration

#### Task 4: Shared checkpoint message builder [x]

Add to `teleclaude/hooks/checkpoint.py`:

- `build_checkpoint_message(git_files: list[str], timeline: TurnTimeline, context: CheckpointContext) -> str`
  - Calls `run_heuristics()` to get the result
  - Formats the result into the message structure defined in R9:
    - Header → changed files summary → required actions → observations → capture reminder
  - Handles special cases: all-clear, no code changes, git diff failure
- `get_checkpoint_content(transcript_path: Optional[str], agent_name: AgentName, project_path: str, working_slug: Optional[str]) -> str`
  - Top-level entry point for both delivery routes
  - Calls `_get_uncommitted_files()` (git subprocess)
  - Calls `transcript.extract_tool_calls_current_turn()` (from transcript.py)
  - Calls `build_checkpoint_message()` (message builder)
  - Returns the formatted checkpoint string
  - Fail-open: any exception returns the generic Phase 1 checkpoint message

**Verify:** Integration tests with mock git output and fixture transcripts producing expected messages.

#### Task 5: Hook route integration (Claude/Gemini) [x]

Modify `_maybe_checkpoint_output()` in `receiver.py`:

1. Resolve transcript path and session context (working_slug, agent_name, project_path)
2. Call `get_checkpoint_content()` from the shared module
3. Use the returned message as the checkpoint reason in the block/deny JSON
4. Keep 30-second timing behavior unchanged
5. Keep escape hatch: when `stop_hook_active=True`, always return pass-through

The receiver already has DB access via `_get_session_from_db()`. Extract `native_log_file`, `working_slug`, and `project_path` from the session record to pass to the shared builder.

**Verify:** Hook tests assert JSON shape with context-aware message content. Test suppression by providing fixture transcripts where actions were already performed.

#### Task 6: Codex route integration (tmux injection) [x]

Modify `_maybe_inject_checkpoint()` in `agent_coordinator.py`:

1. Call same `get_checkpoint_content()` used by hook route
2. Inject resulting message via `send_keys_existing_tmux`
3. Preserve existing codex dedup and threshold checks

**Verify:** Coordinator tests assert codex receives context-aware content. Verify parity with hook route for same inputs.

#### Task 7: Escape hatch behavior (single block per turn) [x]

Ensure the `stop_hook_active` escape hatch in `_maybe_checkpoint_output()`:

1. When `stop_hook_active` is True, always return pass-through (`None`)
2. Do not re-block based on dirty working tree or any heuristic
3. Keep commit/pre-commit as the strict enforcement layer

**Verify:** Unit tests confirm second stop always passes and does not deadlock regardless of git/transcript state.

### Phase C: Verification

#### Task 8: Comprehensive tests [x]

Add/adjust tests across test files:

**File categorization tests (test_checkpoint_builder.py):**

- `test_daemon_code_maps_to_restart` — `teleclaude/core/foo.py` → restart instruction
- `test_hook_runtime_no_action` — `teleclaude/hooks/receiver.py` → no action
- `test_tui_code_maps_to_sigusr2` — `teleclaude/cli/tui/app.py` → SIGUSR2
- `test_telec_setup_maps_to_init` — `teleclaude/project_setup/hooks.py` → telec init
- `test_agent_artifacts_maps_to_restart` — `agents/skills/foo/SKILL.md` → agent-restart
- `test_config_maps_to_restart` — `config.yml` → make restart
- `test_dependencies_maps_to_install` — `pyproject.toml` → pip install
- `test_docs_only_maps_to_capture` — `docs/foo.md` → capture-only
- `test_empty_diff_returns_capture` — no changes → capture-only

**Transcript extraction tests (test_transcript_extraction.py) — tests for transcript.py Layer 2:**

- `test_extract_claude_jsonl_tool_calls` — fixture with Bash/Read/Edit entries
- `test_extract_gemini_json_tool_calls` — fixture with Gemini format
- `test_extract_codex_jsonl_tool_calls` — fixture with Codex format
- `test_extract_missing_transcript_returns_empty` — fail-open
- `test_extract_scopes_to_current_turn` — entries before last user message are excluded
- `test_extract_bounded_read_for_large_jsonl` — tail reader doesn't load full file
- `test_tool_use_result_pairing` — tool_use followed by tool_result produces correct had_error and snippet
- `test_tool_use_without_result` — unpaired tool_use gets had_error=False and empty snippet
- `test_existing_renderers_unaffected` — existing render_agent_output still works after changes (regression guard)

**Verification gap tests (test_checkpoint_builder.py):**

- `test_restart_suppressed_when_make_restart_in_transcript` — evidence found → suppress
- `test_restart_not_suppressed_when_absent` — no evidence → instruction + observation
- `test_sigusr2_suppressed_when_pkill_in_transcript` — evidence found → suppress
- `test_log_check_suppressed_when_instrukt_ai_logs_in_transcript` — evidence found → suppress
- `test_test_instruction_suppressed_when_pytest_in_transcript` — evidence found → suppress
- `test_all_suppressed_emits_all_clear` — everything done → minimal message

**Error state — Layer 1 gate tests (test_checkpoint_builder.py):**

- `test_is_error_false_never_triggers_observation` — successful command with tracebacks in output → silent
- `test_is_error_true_unresolved_emits_observation` — failed tool call with no follow-up → observation
- `test_is_error_resolved_by_bash_retry_suppressed` — failed, then Bash command targeting same area → suppressed
- `test_is_error_resolved_by_edit_suppressed` — failed, then Edit for same file path → suppressed
- `test_is_error_resolved_by_command_rerun_suppressed` — pytest fails, then pytest runs again → suppressed
- `test_multiple_errors_only_last_unresolved_fires` — first error resolved, second unresolved → one observation

**Error state — Layer 2 enrichment tests (test_checkpoint_builder.py):**

- `test_enrichment_traceback_pattern` — unresolved error with Traceback → "Python errors remain"
- `test_enrichment_syntax_error` — unresolved error with SyntaxError → "Syntax errors remain"
- `test_enrichment_import_error` — unresolved error with ImportError → "Import errors remain"
- `test_enrichment_pytest_failure` — unresolved pytest error → "Test failures remain"
- `test_enrichment_unknown_error` — unresolved error without known pattern → generic "command returned errors"
- `test_enrichment_only_fires_when_layer1_fires` — successful command with SyntaxError in stdout → no enrichment, no observation

**Error state — workflow scenario tests (test_checkpoint_builder.py):**

- `test_test_fix_test_cycle_is_silent` — pytest fail → edit → pytest pass → stop: nothing fires
- `test_log_check_with_daemon_tracebacks_is_silent` — instrukt-ai-logs succeeds with tracebacks in output → silent
- `test_make_status_with_warnings_is_silent` — make status succeeds with warnings → silent
- `test_partial_fix_still_fires` — pytest fails 3 tests → fix 2 → pytest fails 1 → stop: observation fires for remaining failure

**Edit hygiene tests (test_checkpoint_builder.py):**

- `test_edit_without_read_emits_observation` — Edit tool call without preceding Read
- `test_edit_with_read_suppressed` — Read then Edit → no observation
- `test_write_without_read_not_flagged` — Write (new file) is OK without Read
- `test_wide_blast_radius_emits_observation` — 4+ top-level dirs → observation
- `test_narrow_blast_radius_suppressed` — 2 dirs → no observation

**Working slug tests (test_checkpoint_builder.py):**

- `test_slug_drift_emits_observation` — zero overlap with plan → observation
- `test_slug_partial_overlap_suppressed` — some overlap → no observation
- `test_no_slug_skips_check` — no working_slug → no observation
- `test_missing_plan_skips_check` — plan file doesn't exist → no observation

**Message composition tests (test_checkpoint_builder.py):**

- `test_message_action_precedence_is_deterministic` — actions follow fixed order
- `test_message_observations_separate_from_actions` — observations in own section
- `test_message_concise` — each observation is one sentence
- `test_all_clear_message_is_minimal` — suppressed everything → short message

**Integration tests (test_checkpoint_hook.py, test_agent_coordinator.py):**

- `test_hook_uses_context_aware_message` — receiver produces rich checkpoint
- `test_codex_uses_context_aware_message` — coordinator produces same content
- `test_hook_codex_parity` — same inputs → equivalent output
- `test_escape_hatch_second_stop_always_passes` — stop_hook_active → pass-through
- `test_git_diff_failure_is_fail_open` — subprocess error → generic checkpoint
- `test_transcript_failure_is_fail_open` — bad transcript → file-based instructions only

**Verify:** `pytest tests/unit/test_transcript_extraction.py tests/unit/test_checkpoint_builder.py tests/unit/test_checkpoint_hook.py tests/unit/test_agent_coordinator.py -q` all green.

#### Task 9: Update design doc [x]

Update `docs/project/design/architecture/checkpoint-system.md`:

- Add Phase 2 two-axis signal model (git diff + transcript) to design overview
- Add transcript scanner to Primary flows section
- Add heuristic engine flow: categorize → suppress → observe → compose
- Add `CheckpointResult` and `TurnTimeline` to Inputs/Outputs
- Add suppressibility invariant to Invariants
- Add failure modes: transcript unavailable, git unavailable, large transcript
- Add Mermaid flow diagram showing the two-axis merge

**Verify:** `telec sync` succeeds.

## Risks and Assumptions

- **Assumption:** `git` is available on PATH in the hook receiver's subprocess environment. If not, fail-open returns generic checkpoint.
- **Assumption:** Checkpoint is guidance and gating, while test enforcement remains at commit/pre-commit.
- **Assumption:** Transcript files use the normalized entry format produced by existing `_iter_*_entries()` functions. Format changes in agent runtimes may require scanner updates.
- **Risk:** Git diff might include staged but not committed files — `git diff --name-only HEAD` includes both staged and unstaged changes relative to HEAD, which is the correct behavior for "uncommitted work."
- **Risk:** Large transcripts could slow the checkpoint. Mitigated by the 512KB tail-read bound for JSONL.
- **Risk:** Substring evidence matching could produce false suppressions (e.g., `make restart` appearing in a comment rather than a command). Acceptable: false suppressions are better than false negatives (per R8).
- **Risk:** The "edit without read" heuristic may fire when the agent read the file in a previous turn. This is intentional — each turn should re-read before editing to ensure the agent has current state.
