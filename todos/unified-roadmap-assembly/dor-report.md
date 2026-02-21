# DOR Report: unified-roadmap-assembly

## Draft Assessment

**Phase:** Draft
**Date:** 2026-02-21

### Gate Analysis

| Gate               | Status | Notes                                                                        |
| ------------------ | ------ | ---------------------------------------------------------------------------- |
| Intent & success   | Pass   | Problem, goal, and success criteria are concrete and testable                |
| Scope & size       | Pass   | Single-session work: extract function, update 2 files, add flags             |
| Verification       | Pass   | Unit tests for core function + CLI flag behavior + existing test suite       |
| Approach known     | Pass   | Pattern is clear: extract sync function, thin async wrapper, CLI consumes it |
| Research complete  | N/A    | No third-party dependencies                                                  |
| Dependencies       | Pass   | Depends on mcp-to-tool-specs (set in roadmap.yaml)                           |
| Integration safety | Pass   | Internal refactor — data model unchanged, API contract unchanged             |
| Tooling impact     | Pass   | CLI flags added to CLI_SURFACE; pre-commit hook validates automatically      |

### Assumptions

1. `command_handlers.list_todos()` can be split into sync core + async wrapper without behavior change
2. The breakdown/container-child injection logic transfers cleanly to the sync function
3. `TodoInfo` shape is sufficient for both CLI rendering and JSON wire format (no new fields needed)

### Open Questions

None — the codebase exploration in this session resolved all unknowns.

### Risks

- The `list_todos()` function is ~250 lines with nested helpers; extraction must be careful to preserve all edge cases (orphan dirs, icebox exclusion, breakdown injection)
- CLI rendering format is a design choice — the builder should match the TUI's information density without Rich/Textual dependencies

### Recommendation

Ready for gate validation. All DOR gates appear satisfied.
