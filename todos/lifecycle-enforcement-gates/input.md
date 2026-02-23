# Lifecycle Enforcement Gates

## The Problem

The lifecycle has gates documented in procedures but nothing enforces them. The builder checks boxes, the reviewer validates boxes are checked, nobody runs the actual gates. The state machine trusts the builder's word.

This was exposed when `discord-media-handling` was delivered without a working demo — the builder lied on the quality checklist ("No demo.md" when one existed), the reviewer didn't catch it, the orchestrator accepted it, and the demo artifacts were deleted during cleanup.

## What Needs to Change

### 1. Demo Lifecycle (End-to-End Fix)

**Prepare phase:** The architect drafts `demo.md` with section headings and HTML comments describing what needs to be demonstrated functionally. No executable code blocks — the architect doesn't know the code yet. Just intent: what medium (CLI, TUI, web, API), what the user should observe, what proves it works.

**Build phase:** The builder owns making `demo.md` executable. They replace HTML comment placeholders with real bash code blocks. This is a build deliverable, not optional.

**State machine gate:** After the builder reports BUILD COMPLETE but before the orchestrator marks `build=complete`, the state machine runs `telec todo demo {slug}` in the worktree. If it fails (non-zero exit), build is NOT complete — the builder stays active and gets sent back to fix it. If it passes, build proceeds to review.

**`telec todo demo` fix:** Currently exits 0 when no executable blocks are found (lines 1318-1320, 1330-1332 in telec.py). Must exit non-zero instead. A demo.md with no executable blocks is a failure, not a pass.

**Review phase:** The reviewer inspects `demo.md` content quality — are the blocks testing the right things? Do they cover the delivery? The reviewer doesn't run them (proven by the build gate), but evaluates whether they're meaningful.

**Finalize phase:** The finalizer promotes `todos/{slug}/demo.md` to `demos/{slug}/demo.md` and generates `snapshot.json` with metrics from git diff-stats, state.yaml review rounds, and narrative acts. This happens after merge/push but before delivery logging.

### 2. `make test` as Machine-Enforced Build Gate

The builder claims "tests pass" in the quality checklist, but nobody verifies. The worktree is isolated — `make test` there catches everything, including regressions unrelated to the current work.

The state machine should run `make test` in the worktree as a build gate, same pattern as demo validation. If tests fail, build is not complete — builder stays and fixes.

This is about catching problems before they hit review, not trusting self-reported checkboxes.

### 3. GitHub Actions as Review/Finalize Gate

Review can currently approve even if CI is red. Nothing checks GitHub Actions status before finalize.

After the branch is pushed and CI runs, the state machine should verify the GitHub Actions run passed before allowing review to approve. If CI fails after review, it should bounce back to fix-review cycle, not proceed to finalize.

Most of our software has a GitHub endpoint. The run must be green.

### 4. Definition of Done — Teeth at Every Layer

The quality checklist template and DoD documentation need to reflect that these gates are machine-enforced, not self-reported:

- **Build gates enforced by the machine:** demo validation, `make test`
- **Review/finalize gates enforced by CI:** GitHub Actions green
- **Finalize gates enforced by the machine:** demo promotion to `demos/{slug}/`

The awareness needs to exist in:

- The lifecycle overview procedure
- The build procedure
- The review procedure
- The finalize procedure
- The demo procedure and spec
- The quality checklist template
- The state machine code

## Files Affected

### Code changes:

- `teleclaude/cli/telec.py` — `telec todo demo` fail on no executable blocks
- `teleclaude/core/next_machine/core.py` — demo gate, make-test gate, CI gate between build/review/finalize

### Procedure changes:

- `docs/.../lifecycle/demo.md` — fix responsibility chain
- `docs/.../lifecycle/build.md` — tighten demo and test ownership
- `docs/.../lifecycle/review.md` — add demo quality inspection, CI gate awareness
- `docs/.../lifecycle/finalize.md` — add demo promotion step
- `docs/.../lifecycle-overview.md` — reflect enforcement
- `docs/.../maintenance/next-prepare-draft.md` — clarify demo.md is intent only, no code blocks

### Spec/template changes:

- `docs/project/spec/demo-artifact.md` — fix lifecycle description
- `templates/todos/quality-checklist.md` — reflect machine-enforced gates
- `templates/todos/demo.md` — ensure template matches the intent-only pattern

## Origin

Discovered during `/next-work discord-media-handling` delivery on 2026-02-23. The demo was drafted by the architect, ignored by the builder, missed by the reviewer, and deleted during cleanup. The delivery shipped without a working demo.
