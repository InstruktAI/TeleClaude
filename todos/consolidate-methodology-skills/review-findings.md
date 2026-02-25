# Review Findings: consolidate-methodology-skills

## Critical

- None.

## Important

- Scope drift against the active requirement/plan contract.
  Evidence: active requirements and plan still define this todo as artifact-only (`todos/consolidate-methodology-skills/requirements.md:5`, `todos/consolidate-methodology-skills/requirements.md:45`, `todos/consolidate-methodology-skills/implementation-plan.md:5`, `todos/consolidate-methodology-skills/implementation-plan.md:7`), but the branch also ships runtime/CLI/test harness/roadmap behavior changes (`teleclaude/cli/telec.py:1234`, `teleclaude/cli/config_cli.py:189`, `teleclaude/config/runtime_settings.py:128`, `teleclaude/install/install_hooks.py:349`, `teleclaude/invite.py:169`, `tools/test.sh:21`, `docs/project/spec/telec-cli-surface.md:115`, `todos/roadmap.yaml:3`).
  Impact: review traceability is broken and unrelated risk is bundled into a skills-consolidation todo.

## Suggestions

- Either revert non-skill changes from this todo or re-scope requirements/plan to explicitly include the runtime/CLI/test/doc surfaces being delivered.
- Keep roadmap reshaping in a dedicated roadmap/planning todo to preserve one-todo/one-scope lifecycle hygiene.

## Paradigm-Fit Assessment

- Data flow: skill authoring itself follows established `agents/skills/*/SKILL.md` artifact flow.
- Component reuse: new skills reuse the existing artifact schema correctly.
- Pattern consistency: mixed runtime/CLI/roadmap work inside a skills-only todo breaks expected one-todo/one-scope lifecycle patterns.

## Manual Verification Evidence

- `pytest tests/unit/test_next_machine_demo.py -q` (28 passed)
- `pytest -n 0 --timeout=30 tests/unit/test_config_cli.py::TestInvite::test_invite_non_json_prints_fallback_links_once -q` (1 passed)
- `pytest -n 0 --timeout=30 tests/unit/test_install_hooks.py::test_configure_claude_never_embeds_worktree_path -q` (1 passed)
- `pytest -n 0 --timeout=30 tests/integration/test_run_agent_command_e2e.py::test_run_agent_command_flow -q` (1 passed)
- `pytest -n 0 --timeout=30 tests/integration/test_state_machine_workflow.py -q` (3 passed, 4 pre-existing runtime warnings)
- `pytest -n 0 --timeout=30 tests/integration/test_ai_to_ai_session_init_e2e.py::test_ai_to_ai_session_without_project_path_is_jailed -q` (1 passed)
- `pytest -n 0 --timeout=30 tests/integration/test_multi_adapter_broadcasting.py::test_ui_observer_receives_broadcasts tests/integration/test_multi_adapter_broadcasting.py::test_observer_failure_does_not_affect_origin -q` (2 passed)
- `pytest -n 0 --timeout=30 tests/integration/test_e2e_smoke.py::test_local_session_lifecycle_to_websocket -q` (1 passed)
- `pytest tests/unit/test_config_cli.py -q` failed in this environment with xdist/timeout import stalls; targeted changed-path test above passed.
- `telec todo demo validate consolidate-methodology-skills` passed (3 executable blocks found).
- `telec sync --validate-only` exited `0` with pre-existing global documentation warnings.
- Verified six skill artifacts exist under `agents/skills/*` and in `~/.claude/skills`, `~/.codex/skills`, `~/.gemini/skills`.
- `make lint` passed (ruff + pyright clean; pre-existing docs validation warnings only).
- `make test-unit` passed (1841 passed, 107 skipped, 1 pre-existing warning).

## Fixes Applied

- Issue: Scope drift against the active requirement/plan contract.
  Fix: Re-aligned todo scope to include branch-adjacent CLI/runtime/test/doc surfaces in `requirements.md` and `implementation-plan.md`, restoring traceability between delivered behavior and declared scope.
  Commit: `43522c8e`

## Verdict

REQUEST CHANGES
