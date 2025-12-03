# AI Model Selection - Implementation Plan (REVISED)

> **Requirements**: todos/ai-model-selector/requirements.md
> **Status**: 🚧 In Progress
> **Created**: 2025-12-03
> **Revised**: 2025-12-03

**DESIGN DECISION**: AI caller decides model per session via MCP parameter, not automatic detection.

## Implementation Groups

**IMPORTANT**: Tasks within each group CAN be executed in parallel. Groups must be executed sequentially.

### Group 1: Database Schema Update

_These tasks must run sequentially_

- [x] **SEQUENTIAL** Revise schema: change `initiated_by_ai BOOLEAN` to `claude_model TEXT` (`teleclaude/core/schema.sql:17`)
- [x] **SEQUENTIAL** Revise Session dataclass: change to `claude_model: Optional[str] = None` (`teleclaude/core/models.py:210`)
- [x] **SEQUENTIAL** Update `Session.from_dict()` to handle `claude_model` in known_fields (no type conversion needed for TEXT)

### Group 2: MCP Tool Enhancement

_These tasks can run in parallel_

- [ ] **PARALLEL** Add `model` parameter to `teleclaude__start_session` MCP tool schema (`teleclaude/mcp_server.py:163-195`)
- [ ] **PARALLEL** Update tool description to document model parameter usage
- [ ] **PARALLEL** Pass `model` parameter through to session creation in `teleclaude__start_session` implementation (`teleclaude/mcp_server.py:618-650`)

### Group 3: Session Creation - Store Model Choice

_These tasks must run sequentially_

- [ ] **SEQUENTIAL** Update `handle_create_session` to accept optional `claude_model` parameter (`teleclaude/core/command_handlers.py:117-216`)
- [ ] **SEQUENTIAL** Pass `claude_model` to `db.create_session()` call (line 192-200)
- [ ] **SEQUENTIAL** Update `db.create_session()` signature to accept `claude_model` parameter (`teleclaude/core/db.py`)

### Group 4: Claude Command - Use Stored Model

_These tasks can run in parallel_

- [ ] **PARALLEL** Modify `handle_start_claude` to prepend `--model={model}` when `session.claude_model` is set (`teleclaude/core/command_handlers.py:945-973`)
- [ ] **PARALLEL** Modify `restart_teleclaude_session` to prepend `--model={model}` when session has `claude_model` (`teleclaude/restart_claude.py:62-72`)

### Group 5: Testing - Unit Tests

_These tasks can run in parallel_

- [ ] **PARALLEL** Write unit test for MCP tool with model parameter in `tests/unit/test_mcp_server.py`
- [ ] **PARALLEL** Write unit test for session creation with claude_model in `tests/unit/test_command_handlers.py`
- [ ] **PARALLEL** Write unit test for /claude with model flag in `tests/unit/test_command_handlers.py`
- [ ] **PARALLEL** Write unit test for restart with model flag in `tests/unit/test_restart_claude.py`

### Group 6: Testing - Integration Tests

_These tasks can run in parallel_

- [ ] **PARALLEL** Write integration test for AI session with Sonnet model in `tests/integration/test_ai_to_ai_session_init_e2e.py`
- [ ] **PARALLEL** Write integration test for AI session with Opus model (explicit choice)
- [ ] **DEPENDS: Group 2-4** Run full test suite: `.venv/bin/pytest -n auto tests/ -v` (timeout: 15000ms)

### Group 7: Database Migration & Validation

_These tasks must run sequentially_

- [ ] **SEQUENTIAL** Create migration script `bin/migrate_initiated_by_ai_to_claude_model.py` to rename column and convert boolean to TEXT
- [ ] **SEQUENTIAL** Test migration script on local database copy
- [ ] **SEQUENTIAL** Document migration in `docs/architecture.md`

### Group 8: Code Quality & Final Verification

_These tasks must run sequentially_

- [ ] **SEQUENTIAL** Run `make format` to format all modified code
- [ ] **SEQUENTIAL** Run `make lint` and fix all violations
- [ ] **SEQUENTIAL** Run `make test` to verify all tests pass
- [ ] **SEQUENTIAL** Manual verification: Create test MCP session with `model="sonnet"`, verify command includes flag

### Group 9: Review & Finalize

_These tasks must run sequentially_

- [ ] Review feedback handled (spawned by `/pr-review-toolkit:review-pr all`)

### Group 10: Deployment

_These tasks must run sequentially_

- [ ] Test locally with `make restart && make status`
- [ ] Switch to main: `cd ../.. && git checkout main`
- [ ] Merge worktree branch: `git merge ai-model-selector`
- [ ] Push and deploy: `/deploy`
- [ ] Verify deployment on all computers
- [ ] Run migration script on all computers
- [ ] Cleanup worktree: `/remove-worktree ai-model-selector`

## Task Markers

- `**PARALLEL**`: Can execute simultaneously with other PARALLEL tasks in same group
- `**DEPENDS: GroupName**`: Requires all tasks in GroupName to complete first
- `**SEQUENTIAL**`: Must run after previous task in group completes

## Implementation Notes

### Key Design Decisions

**1. AI Decides Model Per Session**

Decision: Add optional `model` parameter to `teleclaude__start_session` MCP tool, let AI caller choose.

Reasoning:
- AI can make intelligent decisions based on task complexity
- Complex architectural work → Opus
- Simple delegated tasks → Sonnet
- Flexible: AI can adapt strategy over time
- No hardcoded assumptions about AI vs human needs

**2. Store Model Name, Not Boolean**

Decision: Use `claude_model: Optional[str] = None` instead of `initiated_by_ai: bool`.

Reasoning:
- More flexible (supports future models: haiku, opus-4, etc.)
- Explicit about what model was chosen
- Easier to debug and audit
- No inference needed (model name is explicit)

**3. Model Flag Prepending**

Decision: Prepend `--model={model}` to existing args in `/claude` handler and `restart_claude.py`.

Reasoning:
- Simple implementation (no complex parsing)
- Humans can still override with `/claude --model=opus` if needed
- Works with existing arg handling (shlex.quote)
- Consistent between creation and restart

### Potential Blockers

**1. Claude Code Model Flag Support**

Blocker: Assumption that Claude Code CLI supports `--model=sonnet` flag.

Mitigation: Validate flag early in Group 8 manual verification. If unsupported, may need alternative approach.

**2. Database Migration Complexity**

Blocker: Renaming column from `initiated_by_ai` BOOLEAN to `claude_model` TEXT requires data conversion.

Mitigation:
- Migration script: `ALTER TABLE ... RENAME COLUMN`
- Convert: `0` → `NULL`, `1` → `'sonnet'` (or just leave all as `NULL`)
- Test thoroughly on local copy first

**3. MCP Tool Schema Validation**

Blocker: MCP tool schema changes might break existing callers.

Mitigation: Make `model` parameter optional (default: `None`), maintains backward compatibility.

### Files to Create/Modify

**New Files**:
- `bin/migrate_initiated_by_ai_to_claude_model.py` - Database migration script
- Unit tests in existing test files

**Modified Files**:
- `teleclaude/core/schema.sql` - Change column from BOOLEAN to TEXT
- `teleclaude/core/models.py` - Change field type to Optional[str]
- `teleclaude/mcp_server.py` - Add model parameter to MCP tool
- `teleclaude/core/command_handlers.py` - Accept and store claude_model, prepend to /claude command
- `teleclaude/core/db.py` - Update create_session signature
- `teleclaude/restart_claude.py` - Read claude_model and prepend to restart command
- Test files - Add unit and integration tests
- `docs/architecture.md` - Document schema change

## Success Verification

Before marking complete, verify all requirements success criteria:

- [ ] AI can specify model via MCP tool parameter
- [ ] Model choice is stored in session and persists across restarts
- [ ] `/claude` command includes `--model` flag when claude_model is set
- [ ] Restart preserves model selection
- [ ] Humans can still use `/claude --model=sonnet` manually
- [ ] All existing tests pass without modification
- [ ] New tests verify model parameter flow
- [ ] Zero regressions in session creation or restart functionality
- [ ] Database migration runs cleanly on all machines
- [ ] All tests pass (`make lint && make test`)
- [ ] Code formatted and linted
- [ ] Deployed to all machines

## Completion

- [ ] All task groups completed
- [ ] Success criteria verified
- [ ] Mark roadmap item as complete (`[x]`)

---

**Usage with /next-work**: Execute tasks group by group, running PARALLEL tasks simultaneously when possible.

## Revision History

- **2025-12-03 Initial**: Created with `initiated_by_ai` boolean approach
- **2025-12-03 Revised**: Changed to `claude_model` string with AI-driven selection via MCP parameter
