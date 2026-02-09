# Context-Aware Checkpoint (Phase 2) — Implementation Plan

## Approach

Introduce a shared context-aware checkpoint builder used by both delivery paths:

- Hook path (`receiver.py`) for Claude/Gemini
- Tmux injection path (`agent_coordinator.py`) for Codex

Both paths will inspect `git diff --name-only HEAD`, map changed files to instructions, and emit equivalent checkpoint guidance. No pytest execution occurs inside hook/coordinator checkpoint logic.

## Files to Change

| File                                                    | Change                                                                           |
| ------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `teleclaude/hooks/receiver.py`                          | Use shared context-aware message builder with single-block-per-turn escape hatch |
| `teleclaude/core/agent_coordinator.py`                  | Use shared context-aware message builder for codex tmux injection                |
| `teleclaude/constants.py`                               | Add/adjust constants for file category patterns and instruction precedence       |
| `tests/unit/test_checkpoint_hook.py`                    | Add/adjust tests for hook route behavior                                         |
| `tests/unit/test_agent_coordinator.py`                  | Add tests for codex route parity and context-aware injection                     |
| `docs/project/design/architecture/checkpoint-system.md` | Update to document Phase 2 context-aware flow                                    |

## Task Sequence

### Task 1: Define shared checkpoint mapping constants

Add to `teleclaude/constants.py`:

- File category patterns as a data structure (list of tuples: category name, include patterns, exclude patterns, instruction template)
- Ensure daemon bucket excludes `teleclaude/hooks/**` and `teleclaude/cli/tui/**`
- Add explicit hook runtime bucket for `teleclaude/hooks/**` (no restart action)
- Ensure artifact categories reflect repo reality: `agents/**`, `.agents/**`, and `**/AGENTS.master.md`
- Add telec-setup category that maps to `telec init` when watchers, hook installers, or git-filter setup files change.

**Verify:** Import succeeds, no syntax errors.

### Task 2: Add shared context-aware checkpoint builder

Add helper(s) in a shared module (or existing appropriate module) and wire both routes to use it:

- `_get_uncommitted_files() -> list[str]` — runs `git diff --name-only HEAD` via subprocess, returns list of changed file paths. Returns empty list on error (fail-open).
- `_categorize_files(files: list[str]) -> list[tuple[str, str]]` — maps file list against category patterns, returns deduplicated list of instructions.
- `build_checkpoint_message(files: list[str]) -> str` — returns context-aware checkpoint guidance text.
  - Always emit required actions in fixed execution precedence:
    1. Runtime/setup actions in strict sub-order (`telec init` → `make restart`/`make status` → TUI `SIGUSR2` → `agent-restart`, only when applicable)
    2. Log-check action (`instrukt-ai-logs teleclaude --since 2m`)
    3. Validation actions
    4. Commit only after steps 1-3
  - Always include baseline non-blocking log-check instruction with concrete command.

**Verify:** Unit tests for categorization and message composition with various file lists.

### Task 3: Hook route integration (Claude/Gemini)

Modify `_maybe_checkpoint_output()` in `receiver.py`:

1. Call shared helper to compute changed-file categories and message text
2. Return agent-specific block/deny JSON using that message
3. Keep 30-second timing behavior unchanged

**Verify:** Hook tests assert JSON shape and context-aware message content.

### Task 4: Codex route integration (tmux injection)

Modify `_maybe_inject_checkpoint()` in `agent_coordinator.py`:

1. Call same shared helper used by receiver
2. Inject resulting context-aware message via `send_keys_existing_tmux`
3. Preserve existing codex dedup and threshold checks

**Verify:** Coordinator tests assert codex receives context-aware content and unchanged timing rules.

### Task 5: Escape hatch behavior (single block per turn)

Modify the `stop_hook_active` escape hatch path in `_maybe_checkpoint_output()`:

1. When `stop_hook_active` is True, always return pass-through (`None`)
2. Do not re-block based on dirty working tree state
3. Keep commit/pre-commit as the strict enforcement layer

**Verify:** Unit tests confirm second stop always passes and does not deadlock.

### Task 6: Update tests

Add/adjust tests:

- `test_git_diff_empty_returns_generic_message` — no changes → capture-only
- `test_message_always_includes_log_check` — all checkpoints include baseline log-check instruction
- `test_message_log_check_command_is_concrete` — includes `instrukt-ai-logs teleclaude --since 2m`
- `test_message_action_precedence_is_deterministic` — actions follow fixed execution order regardless of pattern discovery order
- `test_message_precedence_is_explicit` — message text makes clear what must be done first
- `test_runtime_setup_suborder_is_fixed` — runtime/setup actions preserve strict sub-order when multiple categories match
- `test_daemon_code_change_instructs_restart` — `teleclaude/*.py` → "make restart"
- `test_tui_code_change_instructs_sigusr2` — `teleclaude/cli/tui/*.py` → SIGUSR2
- `test_telec_setup_change_instructs_telec_init` — watcher/hook/filter setup changes → `telec init`
- `test_hook_runtime_code_no_restart_instruction` — `teleclaude/hooks/**` does not trigger daemon restart
- `test_agent_artifacts_instructs_restart` — `agents/**`, `.agents/**`, or `**/AGENTS.master.md` → agent-restart
- `test_config_change_instructs_restart` — `config.yml` → "make restart"
- `test_codex_injection_uses_context_aware_message` — codex tmux path uses same mapping/message routine
- `test_escape_hatch_second_stop_always_passes` — `stop_hook_active` always passes through
- `test_git_diff_failure_is_fail_open` — subprocess error → generic checkpoint

**Verify:** `pytest tests/unit/test_checkpoint_hook.py tests/unit/test_agent_coordinator.py -q` all green.

### Task 7: Update design doc

Update `docs/project/design/architecture/checkpoint-system.md`:

- Add Phase 2 context-aware flow to Primary flows section
- Add shared file-mapping logic used by hook and codex paths
- Add context-aware message format to Outputs
- Add uncommitted-changes gate to Invariants
- Update failure modes table with new scenarios (git unavailable, subprocess errors)

**Verify:** `telec sync` succeeds.

## Risks and Assumptions

- **Assumption:** `git` is available on PATH in the hook receiver's subprocess environment. If not, fail-open returns generic checkpoint.
- **Assumption:** checkpoint is guidance and gating, while test enforcement remains at commit/pre-commit.
- **Risk:** git diff might include staged but not committed files — `git diff --name-only HEAD` includes both staged and unstaged changes relative to HEAD, which is the correct behavior for "uncommitted work."
