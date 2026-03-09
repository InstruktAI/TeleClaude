# Implementation Plan: test-suite-overhaul

## Verdict: SPLIT — not directly builder-ready

This todo has been assessed as **not atomic** under DOR Gate 2 (Scope & size).

- **354 source files** across 20+ modules
- **242 existing test files** to triage
- **3,438 test functions** to evaluate
- The input itself proposes 7 workers

No single builder session can process this scope. The parent todo is now a **holder** with 11 child work items.

## Child todos

### Phase 1: Infrastructure (sequential)

| Slug | Scope | Files |
|------|-------|-------|
| `tso-infra` | Feature branch, directory scaffold, conftest, CI enforcement, ignored.md framework | ~10 new files |

### Phase 2: Module workers (parallel, all depend on tso-infra)

| Slug | Scope | Source files |
|------|-------|-------------|
| `tso-adapters` | adapters/, transport/ | ~19 |
| `tso-api` | api/, services/ | ~16 |
| `tso-cli` | cli/ (non-TUI), config/, entrypoints/ | ~21 |
| `tso-tui` | cli/tui/ full tree | ~60 |
| `tso-core-data` | core/ data model layer + migrations | ~59 |
| `tso-core-logic` | core/ behavioral layer + next_machine, operations, integration | ~44 |
| `tso-hooks` | hooks/ full tree | ~23 |
| `tso-peripherals` | channels, chiptunes, cron, deployment, helpers, history, install, memory, mirrors, output_projection, project_setup, runtime, stt, tagging, tools, tts, types, utils, root | ~112 |

### Phase 3: Integration triage (depends on all Phase 2)

| Slug | Scope | Files |
|------|-------|-------|
| `tso-integration` | Triage tests/integration/, enforce cross-module boundary | 29 existing |

### Phase 4: Validation (depends on Phase 3)

| Slug | Scope | Files |
|------|-------|-------|
| `tso-validate` | Full suite validation against all parent success criteria | validation only |

## Dependency DAG

```
test-suite-overhaul (holder)
  └─ tso-infra
       ├─ tso-adapters ──┐
       ├─ tso-api ───────┤
       ├─ tso-cli ───────┤
       ├─ tso-tui ───────┤
       ├─ tso-core-data ─┤
       ├─ tso-core-logic ┤
       ├─ tso-hooks ─────┤
       └─ tso-peripherals┤
                         └─ tso-integration
                              └─ tso-validate
```

## Rationale for split boundaries

- **Module boundaries**: Each worker covers a natural package boundary in the source tree
- **Independent shippability**: Each worker's output (test files) can be committed independently
- **Session size**: Largest worker (tso-peripherals, ~112 files) handles many trivially-exempt files (__init__.py, constants, type definitions). Largest substantive worker (tso-tui, ~60 files) is near the session limit but coherent as one subsystem
- **Coordination cost**: Minimal — workers share conftest (owned by infra) and ignored.md (append-only). No cross-worker file conflicts
- **core/ split**: Data layer vs. behavioral layer follows the natural separation in the module. Both workers write to `tests/unit/core/` but target different source files
