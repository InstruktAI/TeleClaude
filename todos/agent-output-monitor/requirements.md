# Context-Aware Checkpoint (Phase 2) — Requirements

## Problem Statement

The current checkpoint message is generic ("Continue or validate your work if needed..."). Agents dismiss it without running tests, restarting the daemon, or doing any real validation. The checkpoint must be specific about what's expected based on what actually changed AND what the agent actually did during its turn.

Two signal axes drive the checkpoint:

1. **What changed** — git diff reveals which files were modified, mapping to required actions
2. **What the agent did** — transcript inspection reveals whether required actions were already performed, whether errors were ignored, and whether editing practices were sound

The checkpoint is dumb automation — no LLM calls, purely deterministic heuristics — but it produces targeted, specific feedback that points the agent at its next concrete step.

## Intended Outcome

Checkpoint messages at `agent_stop` boundaries include:

1. Context-aware validation instructions based on changed files
2. Specific follow-up actions based on which files changed (restart daemon, SIGUSR2 TUI, agent-restart)
3. Transcript-derived observations that detect verification gaps, ignored errors, and hygiene issues
4. Suppression of instructions the agent already fulfilled (no redundant nagging)
5. The same instruction logic for both delivery paths:
   - Hook route (Claude/Gemini): checkpoint reason JSON
   - Codex route: tmux checkpoint injection
6. Single-block-per-turn escape hatch: first checkpoint may block, second stop must pass through

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
| tests only                           | `tests/**/*.py` with no source changes                                                                                                                                                                                                  | "Run targeted tests for changed test files"                                   |
| agent artifacts                      | `agents/**`, `.agents/**`, `**/AGENTS.master.md`                                                                                                                                                                                        | "Run agent-restart to reload artifacts"                                       |
| config                               | `config.yml`                                                                                                                                                                                                                            | "Run `make restart` + `make status`"                                          |
| dependencies                         | `pyproject.toml`, `requirements*.txt`                                                                                                                                                                                                   | "Install updated dependencies: `pip install -e .`"                            |
| no code changes                      | Only docs, todos, ideas, markdown                                                                                                                                                                                                       | Capture-only message                                                          |

Already-automated triggers (excluded from checkpoint instructions):

- `docs/**/*.md` — `telec sync` runs as pre-commit hook
- `agents/**/*.md` sources — same
- Lint/format — pre-commit hooks

### R3: Transcript Inspection (Second Signal Source)

The agent's transcript is the second signal source alongside git diff. At checkpoint time:

- Read the transcript from the session's `native_log_file` path
- Scope scanning to the current turn only: walk backward from end of transcript until the last user-role message entry; everything after that boundary is the current turn
- Extract a structured timeline of tool calls within the current turn:
  - Tool name (e.g., `Bash`, `Read`, `Edit`, `Write`)
  - Tool input (e.g., `command` string for Bash, `file_path` for Read/Edit/Write)
  - Tool result presence and `is_error` flag
  - Timestamp of each entry
- The scanner must be bounded: for JSONL transcripts, read only the last N kilobytes (e.g., 512KB) and parse from there. Do not load the entire transcript for long sessions.
- For JSON transcripts (Gemini), load the full file but only process entries after the last user boundary.
- Fail-open: if the transcript is missing, unreadable, or in an unexpected format, skip all transcript-based heuristics and emit file-based instructions only.

**Architectural constraint — layered, not parallel:**

The transcript module (`teleclaude/utils/transcript.py`) is the single home for all transcript parsing across all three agent runtimes. The tool-call extraction needed for checkpoints MUST be a new layer in the existing module, not a parallel parser:

```
Layer 0: Raw I/O — _iter_jsonl_entries(), JSON load, tail-read for bounded access
Layer 1: Format normalization — _iter_claude_entries(), _iter_gemini_entries(), _iter_codex_entries()
         All produce common {type, timestamp, message: {role, content: [blocks]}} shape.
Layer 2: Purpose-specific consumers (parallel, sharing Layer 0+1):
         - Rendering: render_agent_output(), parse_*_transcript() [existing]
         - Extraction: extract_last_*_message(), collect_transcript_messages() [existing]
         - Tool call extraction: extract_tool_calls_current_turn() [NEW — this work]
```

The new tool-call extraction function lives in `transcript.py` alongside the existing extraction functions. It walks the same normalized entries, processes the same content blocks, and shares the same per-agent iterators. The checkpoint module (`checkpoint.py`) is a thin consumer that calls into `transcript.py` and never parses transcripts directly.

This ensures:

- One place knows how to read Claude JSONL, Gemini JSON, and Codex JSONL
- Format changes in agent runtimes require updates in one file
- The tail-read optimization (bounded I/O for large transcripts) benefits all consumers
- Future features that need tool-call data from transcripts reuse the same extraction layer

### R4: Verification Gap Detection

For each file-to-action instruction from R2, check the transcript timeline for evidence that the action was already performed during the current turn. Suppress the instruction if evidence is found.

| Category triggered              | Evidence pattern in transcript                                                        | If found                             |
| ------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------ |
| daemon code → restart           | Bash tool call where `command` contains `make restart`, exit not errored              | Suppress restart instruction         |
| daemon code → status            | Bash tool call where `command` contains `make status`, appearing after a restart call | Suppress status instruction          |
| TUI code → SIGUSR2              | Bash tool call where `command` contains `pkill -SIGUSR2` or `kill -USR2`              | Suppress reload instruction          |
| agent artifacts → agent-restart | Bash tool call where `command` contains `agent-restart` or the API curl               | Suppress artifact reload instruction |
| telec setup → telec init        | Bash tool call where `command` contains `telec init`                                  | Suppress init instruction            |
| config → restart                | Same as daemon code restart evidence                                                  | Suppress restart instruction         |
| dependencies → install          | Bash tool call where `command` contains `pip install`                                 | Suppress install instruction         |
| any code change → tests         | Bash tool call where `command` contains `pytest` or `make test`                       | Suppress test instruction            |
| any change → log check          | Bash tool call where `command` contains `instrukt-ai-logs`                            | Suppress log check instruction       |

When an instruction IS suppressed, emit nothing for that action — clean suppression, no "already done" chatter.

When an instruction is NOT suppressed (action was expected but not observed), emit both:

1. The action instruction (in Required Actions)
2. An observation: e.g., "Daemon code was modified but `make restart` was not observed this turn"

### R5: Error State Detection (Two-Layer Model)

Error detection uses a two-layer model to avoid false signals from normal development workflows (test-fix-test cycles, expected errors in log output, informational commands):

**Layer 1 — Structural gate (`is_error` flag):**

Only tool results with `is_error: true` are candidates for error observations. This flag is set by the agent runtime when a command genuinely fails (non-zero exit code, tool execution error). Tool results from successful commands are NEVER scanned for error patterns, even if their content contains tracebacks or error strings (e.g., daemon log output, test framework output during a passing run, informational reads).

For each `is_error: true` result, check whether a subsequent action addressed it:

| Resolution evidence                                                           | Effect    |
| ----------------------------------------------------------------------------- | --------- |
| A later Bash tool call references the same file/module area (substring match) | Suppress  |
| A later Edit/Write tool call targets the same file path                       | Suppress  |
| A later invocation of the same command (e.g., second `pytest` call) exists    | Suppress  |
| No subsequent related action found                                            | → Layer 2 |

**Layer 2 — Content enrichment (patterns inside unresolved errors only):**

When Layer 1 determines an error is unresolved (no suppression evidence found), scan THAT specific error's `result_snippet` to produce targeted feedback. Layer 2 never fires independently — it only enriches Layer 1 decisions.

| Content pattern                                | Enriched feedback                                           |
| ---------------------------------------------- | ----------------------------------------------------------- |
| `Traceback (most recent call last)`            | "Python errors remain unresolved — verify they are fixed"   |
| `SyntaxError`                                  | "Syntax errors remain — verify the code is valid"           |
| `ImportError` or `ModuleNotFoundError`         | "Import errors remain — check dependencies or module paths" |
| Bash command contained `pytest` or `make test` | "Test failures remain — re-run tests after fixes"           |
| None of the above                              | "A command returned errors — verify the issue is resolved"  |

**Why this avoids noise:**

- `instrukt-ai-logs` output contains daemon tracebacks → command succeeded (`is_error: false`) → Layer 1 skips it entirely
- `make status` shows warnings → command succeeded → skipped
- First `pytest` run fails, agent fixes, second `pytest` passes → first error suppressed by second `pytest` call
- Agent fixes code via Edit tool → Edit for same file path counts as resolution evidence
- Only errors near the END of the turn with NO follow-up survive to the checkpoint message

### R6: Edit Hygiene

Scan the transcript timeline for editing practices that indicate potential issues:

| Pattern           | Detection                                                                                                            | Feedback                                                                              |
| ----------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Edit without read | A `file_path` appears in an `Edit` tool call's input but does not appear in any preceding `Read` tool call this turn | "Files were edited without being read first this turn — verify changes are correct"   |
| Wide blast radius | Changed files (from git diff) span more than 3 distinct top-level directories (first path component)                 | "Changes span multiple subsystems — consider committing completed work incrementally" |

Exception: newly created files (`Write` tool, not `Edit`) do not require a preceding `Read`. The heuristic only fires for `Edit` operations, where the agent is modifying existing content it should have read first.

### R7: Working Slug Alignment

When the session has a `working_slug` set:

- Read `todos/{slug}/implementation-plan.md` and extract file paths from the "Files to Change" table
- Compare expected file paths (from the plan) against actual changed files (from git diff)
- If zero overlap between expected and actual changed files → emit: "Active work item `{slug}` expects changes in different files — verify you are working on the right task"
- If partial overlap → do not emit (agent may be making related or prerequisite changes)
- If no implementation plan exists or it has no file table → skip this heuristic entirely

This heuristic is opt-in: it only fires when a working slug is set AND an implementation plan with a file table exists. It catches the "agent drifted to something unrelated" case without being noisy on exploratory work.

### R8: Suppressibility Invariant

Every heuristic follows the same contract:

1. Check for positive evidence that the expected behavior occurred
2. If evidence found → suppress (emit nothing)
3. If evidence NOT found → emit the nudge
4. If evidence is ambiguous or transcript unavailable → emit the nudge (fail-safe)

The fail-safe default is to nudge. False positives (nudging when the agent already did the thing) are tolerable — the agent can quickly verify "I already did that" and move on. False negatives (not nudging when the agent forgot) are worse — unverified work ships.

This means: transcript parsing failures, unexpected formats, or missing data all result in "nudge anyway." The file-based instructions from R2 are the floor; transcript heuristics only suppress, never add new required actions.

### R9: Message Composition

Build a structured checkpoint message from all signal sources:

1. **Header** — "Context-aware checkpoint"
2. **Changed files summary** — grouped by category name (e.g., "daemon code", "TUI code"), not individual file paths
3. **Required actions** — only actions NOT suppressed by transcript evidence, in fixed execution precedence:
   1. Runtime/setup actions in strict sub-order:
      - `telec init` when telec setup files changed
      - `pip install -e .` when dependencies changed
      - `make restart` then `make status` when daemon/config changed
      - `pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"` when TUI changed
      - `agent-restart` when agent artifacts changed
   2. Observability: `instrukt-ai-logs teleclaude --since 2m`
   3. Validation: targeted tests
   4. Commit only after steps 1-3 are complete
4. **Observations** — transcript-derived findings (verification gaps, error state, hygiene issues), each as a single declarative sentence
5. **Capture reminder** — memories/bugs/ideas, as closing note outside numbered actions

Special cases:

- If ALL required actions are suppressed AND no observations fired → emit minimal message: "All expected validations were observed. Commit if ready."
- If nothing code-related changed → capture-only message (still include baseline log check)
- If git diff fails → generic checkpoint (same as current Phase 1 behavior)

Formatting:

- Numbered steps for required actions
- Unnumbered bullet points for observations
- Precedence must remain explicit even if formatting changes
- Message must be concise — each observation is one sentence, not a paragraph

### R10: Test Guidance (No Hook-Time Test Execution)

When code or tests changed:

- Do not run pytest inside checkpoint delivery logic
- Include explicit instruction to run targeted tests for changed behavior (unless suppressed by R4)
- Keep hard enforcement at commit/pre-commit quality gates

### R11: Uncommitted Changes Gate

On the second stop (`stop_hook_active=true` for Claude):

- Do not re-block based on dirty files
- Always pass through on the second stop (single-block-per-turn model)
- Keep dirty-tree enforcement at commit/pre-commit, not in repeated stop-hook blocks

### R12: Existing Behavior Preservation

- The 30-second unified turn timer is unchanged
- Escape hatch invariant: checkpoint may block at most once per turn; second stop must pass through
- Codex still uses tmux injection (no hook mechanism), but now uses the same context-aware checkpoint content as hook agents
- DB-persisted checkpoint state is unchanged
- Fail-open on DB errors is unchanged

## Success Criteria

1. When Python files changed: checkpoint includes explicit validation instructions
2. When daemon code changed and agent did NOT restart: checkpoint instructs "make restart" + observation about missing restart
3. When daemon code changed and agent DID restart: restart instruction is suppressed, no nagging
4. When TUI code changed: checkpoint instructs SIGUSR2 reload (suppressed if already done)
5. When only docs/todos changed: generic capture-only message
6. Hook and codex routes produce equivalent instructions for the same changed-file set
7. Second stop always passes through (no repeated blocking loops)
8. Commit-time hooks remain the hard quality gate for dirty or broken code
9. All existing Phase 1 tests continue to pass
10. When a command failed and the agent moved on: error observation is emitted
11. When files were edited without reading: hygiene observation is emitted
12. When working slug exists but changes don't align: drift observation is emitted
13. When all actions are already done and no issues found: minimal "all clear" message
14. When transcript is unavailable: file-based instructions still work (no regression from Phase 1)
15. New tests cover each heuristic, suppression behavior, transcript scanning, codex parity, and escape hatch

## Constraints

- `receiver.py` is a fresh Python process per hook call — no daemon impact from subprocess overhead
- git subprocess calls must handle missing git gracefully (fail-open)
- Transcript scanning must be bounded in read size — tail the JSONL file, don't load 50MB transcripts fully
- Transcript format varies by agent — scanner must normalize across Claude JSONL, Gemini JSON, Codex JSONL
- Message format must work with both Claude (`<system-reminder>`) and Gemini (retry prompt) delivery
- All heuristics are deterministic — zero LLM calls at checkpoint time
- False positives (nudging unnecessarily) are acceptable; false negatives (missing a gap) are not
- The `working_slug` heuristic requires filesystem access to `todos/{slug}/implementation-plan.md` — must handle missing files gracefully
- Heuristic evidence matching uses substring/pattern checks, not exact equality — favoring recall over precision
