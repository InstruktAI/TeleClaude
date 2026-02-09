# Context-Aware Checkpoint (Phase 2) — Requirements

## Problem Statement

The current checkpoint message is generic ("Continue or validate your work if needed..."). Agents dismiss it without running tests, restarting the daemon, or doing any real validation. The checkpoint must be specific about what's expected based on what actually changed.

## Intended Outcome

Checkpoint messages at `agent_stop` boundaries include:

1. Context-aware validation instructions based on changed files
2. Specific follow-up actions based on which files changed (restart daemon, SIGUSR2 TUI, agent-restart)
3. The same instruction logic for both delivery paths:
   - Hook route (Claude/Gemini): checkpoint reason JSON
   - Codex route: tmux checkpoint injection
4. Single-block-per-turn escape hatch: first checkpoint may block, second stop must pass through

## Requirements

### R1: Git Diff Inspection (Shared Source of Truth)

Before building a checkpoint message on either route:

- Run `git diff --name-only HEAD` (subprocess) to get all uncommitted changed files
- Categorize changed files into action buckets using pattern matching
- Use one shared formatter/mapping routine so hook and codex produce equivalent checkpoint instructions

### R2: File-to-Action Categorization

| Category                             | File Patterns                                                                                                                                                                                                                           | Agent Instruction                                                             |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| daemon code                          | `teleclaude/**/*.py` excluding `teleclaude/hooks/**` and `teleclaude/cli/tui/**`                                                                                                                                                        | "Run `make restart` then `make status`"                                       |
| hook runtime code                    | `teleclaude/hooks/**`                                                                                                                                                                                                                   | _(none — hook runtime changes auto-apply on next hook invocation)_            |
| TUI code                             | `teleclaude/cli/tui/**`                                                                                                                                                                                                                 | "Run `pkill -SIGUSR2 -f -- '-m teleclaude.cli.telec$'`"                       |
| telec setup (watchers/hooks/filters) | `teleclaude/project_setup/**`, `templates/ai.instrukt.teleclaude.docs-watch.plist`, `templates/teleclaude-docs-watch.service`, `templates/teleclaude-docs-watch.path`, `.pre-commit-config.yaml`, `.gitattributes`, `.husky/pre-commit` | "Run `telec init` (setup changed: watchers, hook installers, or git filters)" |
| tests only                           | `tests/**/*.py` with no source changes                                                                                                                                                                                                  | "Run targeted tests for changed behavior before commit"                       |
| agent artifacts                      | `agents/**`, `.agents/**`, `**/AGENTS.master.md`                                                                                                                                                                                        | "Run agent-restart to reload artifacts"                                       |
| config                               | `config.yml`                                                                                                                                                                                                                            | "Run `make restart` + `make status`"                                          |
| no code changes                      | Only docs, todos, ideas, markdown                                                                                                                                                                                                       | Capture-only message                                                          |

Already-automated triggers (excluded from checkpoint instructions):

- `docs/**/*.md` — `telec sync` runs as pre-commit hook
- `agents/**/*.md` sources — same
- Lint/format — pre-commit hooks

### R3: Test Guidance (No Hook-Time Test Execution)

When code or tests changed:

- Do not run pytest inside checkpoint delivery logic.
- Include explicit instruction to run targeted tests for changed behavior.
- Keep hard enforcement at commit/pre-commit quality gates.

### R4: Message Composition

Build a structured checkpoint message from matched categories:

1. Header indicating context-aware checkpoint
2. Changed files list
3. "Required actions" list with strict execution precedence (the order is the contract)
4. Baseline instruction always included: run `instrukt-ai-logs teleclaude --since 2m` and check for errors
5. Deduplicated category instructions appended in deterministic order
6. If nothing code-related changed: capture-only message (still include baseline log check)

Execution precedence (fixed):

1. Runtime/setup actions in strict sub-order:
   - `telec init` when telec setup files changed
   - `make restart` then `make status` when daemon/config changed
   - `pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"` when TUI changed
   - `agent-restart` when agent artifacts changed
2. Observability action (run `instrukt-ai-logs teleclaude --since 2m`)
3. Validation actions (targeted tests)
4. Commit only after steps 1-3 are complete
5. Capture reminder (memories/bugs/ideas) as closing note, not part of required-action numbering

Formatting note:

- Numbering may be used for readability, but precedence must remain explicit even if formatting changes.

### R5: Uncommitted Changes Gate

On the second stop (`stop_hook_active=true` for Claude):

- Do not re-block based on dirty files.
- Always pass through on the second stop (single-block-per-turn model).
- Keep dirty-tree enforcement at commit/pre-commit, not in repeated stop-hook blocks.

### R6: Existing Behavior Preservation

- The 30-second unified turn timer is unchanged
- Escape hatch invariant: checkpoint may block at most once per turn; second stop must pass through
- Codex still uses tmux injection (no hook mechanism), but now uses the same context-aware checkpoint content as hook agents
- DB-persisted checkpoint state is unchanged
- Fail-open on DB errors is unchanged

## Success Criteria

1. When Python files changed: checkpoint includes explicit validation instructions
2. When daemon code changed: checkpoint instructs "make restart"
3. When TUI code changed: checkpoint instructs SIGUSR2 reload
4. When only docs/todos changed: generic capture-only message
5. Hook and codex routes produce equivalent instructions for the same changed-file set
6. Second stop always passes through (no repeated blocking loops)
7. Commit-time hooks remain the hard quality gate for dirty or broken code
8. All existing Phase 1 tests continue to pass
9. New tests cover each file category, shared message composition, codex parity, and the uncommitted-changes gate

## Constraints

- `receiver.py` is a fresh Python process per hook call — no daemon impact from subprocess overhead
- git subprocess calls must handle missing git gracefully (fail-open)
- Message format must work with both Claude (`<system-reminder>`) and Gemini (retry prompt) delivery
