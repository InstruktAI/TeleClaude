# Review Findings: auto-architecture-diagrams

## Round 2

### Critical

None.

### Important

None.

### Suggestions

- [R2-S1] `KNOWN_PACKAGES` in `scripts/diagrams/extract_modules.py:13` is a hardcoded filter. New packages added under `teleclaude/` will be silently excluded from the module dependency graph. Consider auto-discovering packages by listing subdirs that contain `__init__.py`.

- [R2-S2] The `is_table` detection in `scripts/diagrams/extract_data_model.py:39-44` uses OR-logic: either inheriting `SQLModel` OR having `table=True` keyword marks a class as a table. Correct detection requires BOTH conditions. No current impact (all classes in `db_models.py` have both), but could produce false positives if non-table SQLModel classes are added.

- [R2-S3] The roadmap lifecycle diagram shows the `r_DONE` state but has no incoming transition. The DONE transition occurs in the finalize worker, not in `core.py` which is the only file parsed by the state machine extractor.

- [R2-S4] Build and review phase statuses are combined into one state diagram in `extract_state_machines.py`, making `COMPLETE` appear as a dead-end when it is the terminal state for the build phase specifically. Grouping by phase name would improve clarity.

- [R2-S5] `COMMAND_ROLES` in `scripts/diagrams/extract_commands.py:15` is a hardcoded visual role mapping that requires manual maintenance when commands change roles. Only affects node shapes, not edge correctness.

### R1 Findings Resolution

All 5 Round 1 findings were resolved and verified:

| Finding                                   | Status                | Verification                                                                                                                                                                      |
| ----------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1-F1 (runtime matrix wrong adapters dir) | Resolved (`1bf5a2b9`) | Runtime matrix now reads from `teleclaude/hooks/adapters/`, `AGENT_PROTOCOL`, and checkpoint blocking path. Output shows correct per-agent features.                              |
| R1-F2 (hardcoded handler dispatch)        | Resolved (`c68955d6`) | Handler dispatch now extracted from `AgentCoordinator.handle_event()` if/elif chain via AST. All 7 handler mappings match source.                                                 |
| R1-F3 (hardcoded transitions)             | Resolved (`11062dc1`) | Roadmap transitions parsed from `update_roadmap_state` call sites; phase transitions from `POST_COMPLETION` mark_phase instructions; command edges from `format_tool_call` usage. |
| R1-F4 (no type-check coverage)            | Resolved (`22497835`) | `pyrightconfig.json` includes `scripts/diagrams`. Pyright reports 0 errors.                                                                                                       |
| R1-F5 (no regression tests)               | Resolved (`35a74d25`) | 6 regression tests covering all extractors with behavioral assertions. All pass.                                                                                                  |

### Verification Summary

- `make diagrams`: Produces 6 .mmd files in `docs/diagrams/` ✓
- `uv run pytest tests/unit/test_diagram_extractors.py`: 6/6 pass ✓
- `uv run pyright scripts/diagrams/`: 0 errors ✓
- Build gates in quality-checklist.md: All checked ✓
- Implementation plan tasks: All checked ✓
- No deferrals ✓

Verdict: APPROVE
