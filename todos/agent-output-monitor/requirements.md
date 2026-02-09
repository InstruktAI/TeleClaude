# Context-Aware Checkpoint (Phase 2) — Requirements

## Problem Statement

The current checkpoint message is generic ("Continue or validate your work if needed..."). Agents dismiss it without running tests, restarting the daemon, or doing any real validation. The checkpoint must be specific about what's expected based on what actually changed.

## Intended Outcome

Checkpoint messages at `agent_stop` boundaries include:

1. Automated test results when Python files changed
2. Specific follow-up actions based on which files changed (restart daemon, SIGUSR2 TUI, agent-restart)
3. An uncommitted-changes gate on the second stop (escape hatch) that blocks until code changes are committed

## Requirements

### R1: Git Diff Inspection

In `_maybe_checkpoint_output()`, before building the checkpoint message:

- Run `git diff --name-only HEAD` (subprocess) to get all uncommitted changed files
- Categorize changed files into action buckets using pattern matching

### R2: File-to-Action Categorization

| Category        | File Patterns                                                       | Agent Instruction                                       |
| --------------- | ------------------------------------------------------------------- | ------------------------------------------------------- |
| daemon code     | `teleclaude/**/*.py` excluding `hooks/receiver.py` and `cli/tui/**` | "Run `make restart` then `make status`"                 |
| hook code       | `teleclaude/hooks/receiver.py`                                      | _(none — auto-reloads)_                                 |
| TUI code        | `teleclaude/cli/tui/**`                                             | "Run `pkill -SIGUSR2 -f -- '-m teleclaude.cli.telec$'`" |
| tests only      | `tests/**/*.py` with no source changes                              | _(none if green)_                                       |
| agent artifacts | `.claude/agents/**`, `.claude/commands/**`, `.claude/skills/**`     | "Run agent-restart to reload artifacts"                 |
| config          | `config.yml`                                                        | "Run `make restart` + `make status`"                    |
| no code changes | Only docs, todos, ideas, markdown                                   | Capture-only message                                    |

Already-automated triggers (excluded from checkpoint instructions):

- `docs/**/*.md` — `telec sync` runs as pre-commit hook
- `agents/**/*.md` sources — same
- Lint/format — pre-commit hooks

### R3: Automated Test Execution

When any `.py` file has uncommitted changes:

- Run `pytest tests/unit/ -x -q` as a subprocess
- Capture pass/fail status and output
- Apply a 30-second timeout to prevent runaway test suites
- If tests fail: instruction is "Fix failing tests before proceeding" with output
- If tests pass: proceed to follow-up action instructions

### R4: Message Composition

Build a structured checkpoint message from matched categories:

1. Test results line (if applicable): pass count + time, or FAILED + output
2. Changed files list
3. Deduplicated instruction list from matched categories
4. If nothing code-related changed: capture-only message

### R5: Uncommitted Changes Gate

On the second stop (`stop_hook_active=true` for Claude):

- Instead of unconditionally passing through, check `git diff --name-only HEAD`
- If uncommitted `.py` or config changes exist: block again with "Commit your changes before stopping"
- If clean (or only non-gated files like docs/ideas/todos): pass through

### R6: Existing Behavior Preservation

- The 30-second unified turn timer is unchanged
- The escape hatch logic (`stop_hook_active`) gains the uncommitted-changes check but otherwise behaves the same
- Codex still uses tmux injection (no hook mechanism) — Phase 2 enhances only the Claude/Gemini hook path
- DB-persisted checkpoint state is unchanged
- Fail-open on DB errors is unchanged

## Success Criteria

1. When Python files changed: checkpoint includes test results (pass/fail + summary)
2. When daemon code changed: checkpoint instructs "make restart"
3. When TUI code changed: checkpoint instructs SIGUSR2 reload
4. When only docs/todos changed: generic capture-only message
5. When tests fail: checkpoint says "Fix failing tests" with output
6. Second stop with uncommitted code: blocks with "Commit your changes"
7. Second stop with clean state: passes through normally
8. All existing Phase 1 tests continue to pass
9. New tests cover each file category, test execution, message composition, and the uncommitted-changes gate

## Constraints

- `receiver.py` is a fresh Python process per hook call — no daemon impact from subprocess overhead
- pytest timeout must be bounded (30s max) to prevent indefinite blocking
- git subprocess calls must handle missing git gracefully (fail-open)
- Message format must work with both Claude (`<system-reminder>`) and Gemini (retry prompt) delivery
