# Review Findings: consolidate-methodology-skills

## Critical

- None.

## Important

- Scope/contract mismatch between active todo definition and delivered branch behavior.
  Evidence: active requirements and plan define this as skills-only artifact authoring (`todos/consolidate-methodology-skills/requirements.md:5`, `todos/consolidate-methodology-skills/requirements.md:26`, `todos/consolidate-methodology-skills/requirements.md:45`, `todos/consolidate-methodology-skills/implementation-plan.md:5`, `todos/consolidate-methodology-skills/implementation-plan.md:7`), while the same branch delivers additional CLI/runtime/install/test/doc/roadmap changes (`teleclaude/cli/telec.py:163`, `teleclaude/cli/telec.py:1234`, `teleclaude/cli/config_cli.py:189`, `teleclaude/config/runtime_settings.py:128`, `teleclaude/install/install_hooks.py:349`, `teleclaude/invite.py:169`, `tools/test.sh:21`, `docs/project/spec/telec-cli-surface.md:118`, `todos/roadmap.yaml:3`).
  Impact: requirement traceability is broken and non-skill behavior risk is bundled into a todo that explicitly excludes Python/test/runtime scope.
  Required fix: either (a) rescope requirements/plan to explicitly include these surfaces and acceptance criteria, or (b) split/revert non-skill changes from this todo.

## Suggestions

- Keep this todo focused on six skills plus sync/distribution/demo evidence, and move roadmap/runtime/CLI adjustments to dedicated todos.
- If non-skill changes remain in this branch, add explicit requirement bullets and success criteria per changed subsystem before re-review.

## Paradigm-Fit Assessment

- Data flow: the six new skill artifacts follow the established `agents/skills/{slug}/SKILL.md` schema and remain runtime-agnostic.
- Component reuse: skill authoring reuses existing artifact structure and distribution pipeline correctly.
- Pattern consistency: mixing broader CLI/runtime/test/roadmap work into a skills-consolidation todo violates the expected one-todo/one-scope lifecycle pattern.

## Manual Verification Evidence

- `pytest -q tests/unit/test_next_machine_demo.py tests/unit/test_config_cli.py::TestInvite::test_invite_non_json_prints_fallback_links_once tests/unit/test_install_hooks.py::test_configure_claude_never_embeds_worktree_path` -> 30 passed.
- `pytest -n 0 --timeout=30 -q tests/integration/test_run_agent_command_e2e.py::test_run_agent_command_flow tests/integration/test_state_machine_workflow.py tests/integration/test_ai_to_ai_session_init_e2e.py::test_ai_to_ai_session_without_project_path_is_jailed tests/integration/test_multi_adapter_broadcasting.py::test_ui_observer_receives_broadcasts tests/integration/test_multi_adapter_broadcasting.py::test_observer_failure_does_not_affect_origin tests/integration/test_e2e_smoke.py::test_local_session_lifecycle_to_websocket` -> 8 passed, 4 pre-existing runtime warnings.
- `telec todo demo validate consolidate-methodology-skills` -> passed (3 executable blocks found).
- Runtime distribution spot-check for all six skills in `~/.claude/skills`, `~/.codex/skills`, `~/.gemini/skills` -> passed.
- `telec sync --validate-only` -> exit 0 with pre-existing global documentation warnings (no validation errors).
- `make lint` -> passed (`ruff` + `pyright` clean; pre-existing docs validation warnings only).

## Verdict

REQUEST CHANGES
