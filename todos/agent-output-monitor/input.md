# Context-Aware Checkpoint (Phase 2)

## Background

Phase 1 (complete): Hook-based invisible checkpoints. The receiver blocks `agent_stop` with a checkpoint reason delivered natively (Claude: `<system-reminder>`, Gemini: retry prompt). No tmux injection for Claude/Gemini. Codex still uses tmux.

Phase 2 (this): Make the checkpoint message **context-aware** by inspecting `git diff --name-only HEAD` and mapping changed files to specific validation actions. Also adds an uncommitted-changes gate so agents commit their work before stopping.

## Problem

The generic checkpoint message ("validate if needed") is easy to dismiss. Agents (especially Claude) say "Clean. Nothing to capture." without actually running tests, restarting the daemon, or doing any real validation. The checkpoint needs to be specific about what's expected based on what actually changed.

## Design

### Mechanism

In `_maybe_checkpoint_output()` (receiver.py), before building the checkpoint JSON:

1. Run `git diff --name-only HEAD` (subprocess, ~instant) to get all uncommitted changes
2. Categorize changed files into buckets
3. If any `.py` files changed: run `pytest tests/unit/ -x -q` (~10s), capture output
4. Build a specific instruction list from matched categories
5. If uncommitted code changes exist after the agent's response turn: gate the final stop with "Commit your changes"

### What's already automated (excluded from checkpoint)

| Trigger                  | Automation                           | Why we skip                |
| ------------------------ | ------------------------------------ | -------------------------- |
| `docs/**/*.md` changed   | `telec sync` runs as pre-commit hook | Commit fails if sync fails |
| `agents/**/*.md` sources | `telec sync` runs as pre-commit hook | Same                       |
| Lint/format issues       | Pre-commit hooks                     | Commit fails if lint fails |

### Restart requirements by file location

| File                           | Loaded by                          | Restart mechanism                                              |
| ------------------------------ | ---------------------------------- | -------------------------------------------------------------- |
| `teleclaude/hooks/receiver.py` | Fresh Python process per hook call | **None needed**                                                |
| `teleclaude/cli/tui/**`        | TUI process                        | `pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"` (hot reload) |
| All other `teleclaude/**/*.py` | Daemon process (loaded at startup) | `make restart`                                                 |
| `config.yml`                   | Daemon process                     | `make restart`                                                 |

### The exhaustive file-to-action mapping

| Category            | File patterns                                                       | Auto in hook           | Agent instruction                                       |
| ------------------- | ------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------- |
| **daemon code**     | `teleclaude/**/*.py` excluding `hooks/receiver.py` and `cli/tui/**` | Run pytest             | "Run `make restart` then `make status`"                 |
| **hook code**       | `teleclaude/hooks/receiver.py`                                      | Run pytest             | _(none — auto-reloads next invocation)_                 |
| **tui code**        | `teleclaude/cli/tui/**`                                             | Run pytest             | "Run `pkill -SIGUSR2 -f -- '-m teleclaude.cli.telec$'`" |
| **tests only**      | `tests/**/*.py` with no source changes                              | Run pytest             | _(none if green)_                                       |
| **agent artifacts** | `.claude/agents/**`, `.claude/commands/**`, `.claude/skills/**`     | —                      | "Run agent-restart to reload artifacts"                 |
| **config**          | `config.yml`                                                        | —                      | "Run `make restart` + `make status`"                    |
| **tests failed**    | _(any category)_                                                    | pytest output included | "Fix failing tests before proceeding"                   |
| **no code changes** | Only docs, todos, ideas, markdown                                   | —                      | Capture only (memories, ideas, bugs)                    |

### Message composition

1. If any `.py` changed → run `pytest tests/unit/ -x -q`, capture pass/fail + output
2. Build instruction list from matched categories (deduplicated)
3. If tests failed → "Tests FAILED" + output, instruction = "Fix tests first"
4. If tests passed → list follow-up actions (restart, SIGUSR2, agent-restart)
5. If nothing code-related changed → generic capture-only

### Uncommitted changes gate (final stop)

When `stop_hook_active` is true (second stop, escape hatch), instead of unconditionally passing through:

1. Run `git diff --name-only HEAD` to check for uncommitted `.py` or config changes
2. If uncommitted gated changes exist → block again with "Commit your changes before stopping"
3. If clean (or only non-gated files like docs/ideas/todos) → pass through

This ensures every session produces atomic commits for its work.

### Example messages

**Code changed, tests pass:**

> Checkpoint — Tests: 1033 passed (5.1s)
>
> Changed: `teleclaude/core/agent_coordinator.py`, `teleclaude/hooks/receiver.py`
>
> Required:
>
> - Run `make restart` then `make status` (daemon code changed)
>
> Then capture anything worth keeping. If everything is clean, do not respond.

**Tests fail:**

> Checkpoint — Tests: FAILED
>
> ```
> FAILED tests/unit/test_checkpoint_hook.py::test_gemini_format - AssertionError
> ```
>
> Fix the failing tests before proceeding.

**No code changes:**

> Checkpoint — No code changes detected.
>
> Capture anything worth keeping (memories, bugs, ideas). If everything is clean, do not respond.

**Second stop with uncommitted changes:**

> You have uncommitted code changes. Commit your work before stopping.
>
> Changed: `teleclaude/hooks/receiver.py`, `tests/unit/test_checkpoint_hook.py`

## Files to modify

| File                                                    | Change                                                                                                                         |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `teleclaude/hooks/receiver.py`                          | Enhance `_maybe_checkpoint_output()` with git diff inspection, pytest execution, message composition, uncommitted-changes gate |
| `teleclaude/constants.py`                               | May need additional constants for the message templates                                                                        |
| `tests/unit/test_checkpoint_hook.py`                    | Add tests for context-aware message generation, pytest integration, git diff mocking                                           |
| `docs/project/design/architecture/checkpoint-system.md` | Update to document context-aware checkpoint flow                                                                               |

## Session context

This design emerged from a conversation about checkpoint compliance. Research confirmed:

- Claude's stop hook `reason` is delivered as `<system-reminder>` (system-level authority)
- Gemini's AfterAgent `deny` reason is sent as a new prompt (retry turn)
- Both CLIs provide `stop_hook_active` escape hatch to prevent infinite loops
- The Gemini AfterAgent JSON uses top-level `decision`/`reason` (NOT wrapped in `hookSpecificOutput`)
- Phase 1 is implemented and deployed: hook-based invisible checkpoints work for both CLIs
- The "Stop hook error:" label in Claude Code UI is a known upstream bug (issue #12667), not our problem
