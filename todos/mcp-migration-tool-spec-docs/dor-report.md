# DOR Gate Report: mcp-migration-tool-spec-docs

## Gate Verdict: needs_work

**Score:** 5/10
**Assessed:** 2026-02-18
**Blocker count:** 1 hard, 2 soft

---

## Gate Results

### 1. Intent & success — PASS

Clear goal: write 24 tool spec doc snippets across 6 taxonomy groups. Five
concrete success criteria including validation via `telec sync`.

### 2. Scope & size — PASS

Writing 24 markdown files is content-heavy but highly mechanical. Each file
follows the same template from the snippet authoring schema (spec type:
"What it is", "Canonical fields"). Pattern established by existing tool specs:
`history-search.md`, `memory-management-api.md`, `agent-restart.md`, `telec-cli.md`.

### 3. Verification — PASS

`telec sync --validate-only` validates frontmatter and structure. Index
appearance in `docs/index.yaml` confirms registration. Baseline flag
verification for 6 tools.

### 4. Approach known — FAIL (hard blocker)

The implementation plan is an **empty skeleton template**. While the approach
is more self-evident here than for the CLI slug (it's "write docs following
existing pattern"), a builder still needs:

- Task breakdown by group (context, sessions, workflow, infrastructure,
  delivery, channels)
- Template/skeleton for tool spec files
- Source reference: `teleclaude/mcp/tool_definitions.py` contains all 25
  JSON schemas that define parameters, types, and descriptions
- Write order recommendation (baseline tools first for early validation)
- Validation checkpoints between groups

Existing examples that establish the pattern:

- `docs/global/general/spec/tools/history-search.md`
- `docs/global/general/spec/tools/memory-management-api.md`
- `docs/global/general/spec/tools/agent-restart.md`
- `docs/global/general/spec/tools/telec-cli.md`

### 5. Research complete — AUTO-PASS

No third-party dependencies.

### 6. Dependencies & preconditions — CONCERN (soft blocker)

No blocking dependencies in `roadmap.yaml` — correct per roadmap
(phases 1 and 2 run in parallel). However:

Each tool spec requires a `telec` invocation example, but the `telec`
subcommands are being built concurrently in `mcp-migration-tc-cli`. The
builder must either:

1. Write `telec` invocations speculatively based on tc-cli requirements
   (CLI design is documented there), or
2. Use placeholder invocations and update after tc-cli lands.

This coordination gap should be explicit in the plan. The requirements
mention `telec` invocations but don't address that the commands don't
exist yet during parallel execution.

### 7. Integration safety — PASS

Adding documentation files is non-destructive. `telec sync` is idempotent.
No risk to main branch stability.

### 8. Tooling impact — AUTO-PASS

Docs don't change tooling or scaffolding.

---

## Required Actions

1. **[Hard]** Send back to draft: fill in implementation plan with task
   breakdown, template skeleton, source file references, and write order.
2. **[Soft]** Address parallel execution coordination: how to handle
   `telec` invocation examples when CLI doesn't exist yet.
3. **[Soft]** Add explicit reference to `teleclaude/mcp/tool_definitions.py`
   as the authoritative source for parameter schemas.
