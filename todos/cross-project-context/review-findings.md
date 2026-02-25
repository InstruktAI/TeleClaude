# Review Findings: cross-project-context

## Critical

- None.

## Important

- Cross-project `snippet_ids` are still blocked by local project-root gating.
  - Location: `teleclaude/mcp/handlers.py:85`, `teleclaude/mcp/handlers.py:1197`
  - Behavior: `teleclaude__get_context(snippet_ids=["teleclaude/design/architecture"], cwd="/")` returns `ERROR: NO_PROJECT_ROOT` before selector execution.
  - Expected: cross-project IDs should resolve via `~/.teleclaude/projects.yaml` without requiring the caller's cwd to contain `teleclaude.yml`.
  - Evidence: reproduced with `.venv/bin/python` async harness by patching `load_manifest` to include `teleclaude`; `build_context_output` was not called.
  - Fix direction: require local root only for `project/...` IDs; do not root-gate manifest-prefixed cross-project IDs.

- `caller_role` is not authoritative; `human_role` can downgrade admin visibility.
  - Location: `teleclaude/context_selector.py:609`
  - Behavior: `build_context_output(caller_role="admin", human_role="member")` hides `visibility: internal` snippets.
  - Expected: role filtering should follow the resolved `user_role` (`caller_role`) per requirement; admin must always see internal snippets.
  - Evidence: reproduced with `.venv/bin/python` harness; identical data returns internal snippets for `caller_role="admin"` but not when `human_role="member"` is also passed.
  - Risk: migrated sessions defaulted to `user_role=admin` but retaining `human_role=member` become unintentionally restricted.
  - Fix direction: treat `caller_role` as authoritative whenever provided; use `human_role` only as fallback when no `caller_role` is available.

## Suggestions

- Add regression tests for:
  - `teleclaude__get_context(snippet_ids=["teleclaude/design/..."], cwd=<no teleclaude.yml>)` should not fail with `NO_PROJECT_ROOT`.
  - `build_context_output(caller_role="admin", human_role="member")` should still include internal snippets.

## Paradigm-Fit Assessment

- Data flow: cross-project selector flow is largely aligned, but handler pre-gating still imposes local-root coupling on manifest-resolved IDs.
- Component reuse: implementation reuses existing selector/handler seams effectively; no copy-paste duplication concerns observed.
- Pattern consistency: visibility model introduces `user_role` correctly, but fallback to `human_role` mixes old/new authorization paradigms.

## Manual Verification Evidence

- Ran targeted tests:
  - `pytest -q tests/unit/test_context_selector.py tests/unit/test_mcp_get_context.py tests/unit/test_project_manifest.py tests/unit/test_telec_sync.py tests/unit/test_docs_index.py tests/unit/test_help_desk_features.py tests/unit/test_command_handlers.py tests/unit/test_db.py`
  - Result: `155 passed`.
- Ran two focused `.venv/bin/python` harness reproductions for the Important findings above.

## Fixes Applied

- Issue: Cross-project `snippet_ids` were blocked by local project-root gating.
  - Fix: Updated `_snippet_ids_require_project_root` to gate only `project/...` IDs and added regression coverage for `teleclaude/design/architecture` without local `teleclaude.yml`.
  - Commit: `633521be`

- Issue: `caller_role` was not authoritative and could be downgraded by `human_role`.
  - Fix: Updated visibility resolution to use `human_role` only when `caller_role` is absent and added regression coverage for `caller_role="admin", human_role="member"`.
  - Commit: `a395bf5f`

Verdict: REQUEST CHANGES
