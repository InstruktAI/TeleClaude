# Implementation Plan: `teleclaude__next_prepare` HITL Support

## Group 1: Core Logic Changes (`teleclaude/core/next_machine.py`)

- [ ] Add `is_file_committed(cwd: str, relative_path: str) -> bool` helper function
  - Uses `git ls-files` to check if file is tracked by git
  - Returns True only if file exists AND is committed

- [x] Add `format_hitl_guidance(context: str) -> str` helper function after line 117
  - Prefixes context with "Before proceeding, read ~/.agents/commands/next-prepare.md if you haven't already."

- [x] Modify `next_prepare()` function signature (line 366)
  - Add `hitl: bool = True` parameter

- [x] Remove automatic slug resolution for HITL=true mode (lines 381-382)
  - When `hitl=True` and no slug provided, skip `resolve_slug()` call
  - When `hitl=False`, keep existing `resolve_slug()` behavior

- [x] Delete `is_in_progress` check block (lines 397-404)
  - This check doesn't belong in prepare phase

- [x] Replace `next-roadmap` dispatch with `next-prepare` (lines 385-394)
  - Change `command="next-roadmap"` to `command="next-prepare"`
  - Set `args=""`

- [x] Add HITL branching for "no slug" case
  - HITL=true: return `format_hitl_guidance()` with guidance to read roadmap, discuss, write artifacts
  - HITL=false: dispatch `next-prepare` to another AI

- [x] Add HITL branching for "missing requirements.md" case (lines 407-421)
  - HITL=true: return guidance to write requirements.md and implementation-plan.md
  - HITL=false: dispatch `next-prepare {slug}` (existing behavior)

- [x] Add HITL branching for "missing implementation-plan.md" case (lines 424-438)
  - HITL=true: return guidance to write implementation-plan.md
  - HITL=false: dispatch `next-prepare {slug}` (existing behavior)

- [ ] Add check for uncommitted files before PREPARED
  - Use `is_file_committed()` to verify both files are tracked by git
  - If files exist but not committed: return guidance to commit them
  - Only return PREPARED when both files exist AND are committed

## Group 2: MCP Server Integration (`teleclaude/mcp_server.py`)

- [x] Add `hitl` parameter to tool schema (around line 576)
  - Type: boolean, default: true
  - Description: "Human-in-the-loop mode. When true (default), returns guidance for the calling AI to work interactively with the user. When false, dispatches to another AI for autonomous collaboration."

- [x] Extract `hitl` parameter in `call_tool()` method (around line 776)
  - Default to `True` if not provided

- [x] Update `teleclaude__next_prepare()` method signature (around line 2132)
  - Add `hitl: bool = True` parameter

- [x] Pass `hitl` parameter to `next_prepare()` function call (around line 2152)

## Group 3: Testing

- [x] Run `make lint` to verify no lint errors
- [x] Run `make test` to verify existing tests pass
- [x] Add/update unit tests for `next_prepare()` in `tests/unit/`
  - Test HITL=true with no slug
  - Test HITL=true with slug, missing requirements
  - Test HITL=true with slug, missing impl-plan
  - Test HITL=true with both files present but uncommitted
  - Test HITL=true with both files committed (PREPARED)
  - Test HITL=false dispatch behavior
- [x] Run `make test` to verify all tests pass

## Group 4: Verification

- [x] Restart daemon: `make restart`
- [x] Verify daemon running: `make status`
- [x] Manual test: call `teleclaude__next_prepare()` with HITL=true, no slug
- [x] Manual test: call `teleclaude__next_prepare()` with HITL=false

## Files Changed

| File | Changes |
|------|---------|
| `teleclaude/core/next_machine.py` | Add `hitl` param, remove `is_in_progress` check, add HITL branching |
| `teleclaude/mcp_server.py` | Add `hitl` to schema, pass through to function |
| `tests/unit/test_next_machine.py` | Add HITL test cases |

## What Does NOT Change

- `resolve_slug()` function (still needed for `next_work`)
- `format_tool_call()` function (used for HITL=false dispatches)
- `format_prepared()` function (used by both modes)
- `next_work()` function (separate phase)
- `next-prepare.md` command doc (already handles no-slug case)
