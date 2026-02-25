# Review Findings: cross-project-context

## Critical

- Phase 2 cross-project retrieval fails unless `projects=[...]` is redundantly passed again.
  - Location: `teleclaude/context_selector.py:619`
  - Behavior: a request like `snippet_ids=["teleclaude/design/architecture"]` without `projects` is loaded in phase 2, then filtered out by project-path domain gating and emitted as `access: denied`.
  - Expected: requirement success criterion says `get_context(snippet_ids=["teleclaude/design/architecture/checkpoint-system"])` should resolve and return content in phase 2.
  - Evidence: reproduced with concrete values via `.venv/bin/python` harness; output returned denial block instead of snippet body.
  - Fix direction: in `_include_snippet`, allow cross-project snippets that were explicitly requested in phase 2 (or apply domain/path gating only to phase 1 listing, not phase 2 explicit IDs).

## Important

- MCP project-root detection is too broad and rejects non-project snippet IDs.
  - Location: `teleclaude/mcp/handlers.py:1179`
  - Behavior: any `snippet_id` containing `/` except `general/` and `third-party/` triggers `teleclaude.yml` root walk. This includes baseline/domain IDs (e.g. `baseline/...`, `software-development/...`) that are not project-prefixed.
  - Risk: callers outside a TeleClaude project root get `ERROR: NO_PROJECT_ROOT` for valid non-project lookups.
  - Evidence: reproduced with `.venv/bin/python` harness and `snippet_ids=["software-development/policy/commits"]` from `cwd="/tmp"`.
  - Fix direction: align this guard with cross-project/project detection logic (exclude baseline/domain/global IDs, or only enforce root for IDs that truly require project-root resolution).

## Suggestions

- Add regression tests for both failure paths:
  - `build_context_output(snippet_ids=["{project}/..."], projects=None)` should return content in phase 2.
  - `teleclaude__get_context(snippet_ids=["software-development/..."], cwd=<no teleclaude.yml>)` should not fail early with `NO_PROJECT_ROOT`.

## Paradigm-Fit Assessment

- Data flow: implementation mostly follows existing selector/handler boundaries, but phase-2 filtering still reuses phase-1 path-gating assumptions, creating a boundary mismatch.
- Component reuse: no major duplication concerns found.
- Pattern consistency: error reporting shape is consistent, but the current `access: denied` emission for a domain-gating failure is semantically misleading.

## Manual Verification Evidence

- Ran targeted unit suites for touched modules:
  - `pytest -q tests/unit/test_context_selector.py tests/unit/test_mcp_get_context.py tests/unit/test_project_manifest.py tests/unit/test_telec_sync.py tests/unit/test_docs_index.py tests/unit/test_help_desk_features.py tests/unit/test_command_handlers.py tests/unit/test_db.py`
  - Result: `152 passed`.
- Performed focused runtime reproductions with concrete values using `.venv/bin/python` harnesses for both findings above.

Verdict: REQUEST CHANGES

## Fixes Applied

- Critical: Phase 2 cross-project retrieval failed without repeating `projects=[...]`.
  - Fix: Allowed explicitly requested cross-project phase-2 snippet IDs through `_include_snippet` while keeping visibility checks and existing domain gating for non-explicit items.
  - Commit: `ed00a153`
- Important: MCP project-root detection rejected valid non-project snippet IDs.
  - Fix: Replaced broad slash-prefix guard with project-root gating limited to `project/...` and manifest project prefixes.
  - Commit: `d8860b6a`
