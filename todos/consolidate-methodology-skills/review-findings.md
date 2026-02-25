# Review Findings: consolidate-methodology-skills

## Critical

- None.

## Important

- Scope drift beyond approved requirements and plan.
  Evidence: `todos/consolidate-methodology-skills/requirements.md:45` and `todos/consolidate-methodology-skills/implementation-plan.md:7` define this todo as artifact-only with no Python/test work, but this branch also changes runtime and CLI behavior in `teleclaude/cli/telec.py:1234`, `teleclaude/cli/config_cli.py:189`, `teleclaude/config/runtime_settings.py:128`, `teleclaude/install/install_hooks.py:349`, `tools/test.sh:21`, and rewrites roadmap content in `todos/roadmap.yaml:3`.
  Impact: review scope is no longer single-purpose; this bundles unrelated behavioral risk into a skills-consolidation todo and violates lifecycle scope discipline.

- Invite fallback now duplicates link output in non-JSON flows when SMTP credentials are missing.
  Evidence: `teleclaude/invite.py:198` prints invite links when `BREVO_SMTP_USER` is unset, and `teleclaude/cli/config_cli.py:608` prints the same links again when `email_sent` is false.
  Impact: duplicate token-bearing URLs and noisy user feedback for `telec config invite`.

- New CLI behavior for `telec todo demo` is only partially covered by tests.
  Evidence: new parsing and `create`/`validate` modes were added in `teleclaude/cli/telec.py:1256` and `teleclaude/cli/telec.py:1277`, but test additions in `tests/unit/test_next_machine_demo.py:211` cover only `validate`, not `create` or parser compatibility edges.
  Impact: regression risk on user-facing command surface is elevated.

## Suggestions

- Split non-skill runtime/CLI/test-harness changes into dedicated todos (or explicitly re-scope this todo) so requirements, plan, and verification stay aligned.
- Make one layer own invite fallback output (callee or caller), not both.
- Add unit tests for `telec todo demo create` and parser edge cases introduced by mode keywords.

## Paradigm-Fit Assessment

- Data flow: skill authoring itself follows established `agents/skills/*/SKILL.md` artifact flow.
- Component reuse: new skills reuse the existing artifact schema correctly.
- Pattern consistency: this branch mixes unrelated runtime, CLI, and roadmap work into a skills-only todo, which breaks the expected one-todo/one-scope lifecycle pattern.

## Manual Verification Evidence

- `pytest tests/unit/test_next_machine_demo.py -q` (24 passed)
- `pytest tests/unit/test_install_hooks.py -q` (15 passed)
- `pytest tests/integration/test_run_agent_command_e2e.py::test_run_agent_command_flow -q` (1 passed)
- `pytest tests/integration/test_state_machine_workflow.py -q` (3 passed; 4 existing runtime warnings)
- `pytest tests/integration/test_ai_to_ai_session_init_e2e.py::test_ai_to_ai_session_without_project_path_is_jailed -q` (1 passed)
- `pytest tests/integration/test_multi_adapter_broadcasting.py::test_ui_observer_receives_broadcasts tests/integration/test_multi_adapter_broadcasting.py::test_observer_failure_does_not_affect_origin -q` (2 passed)
- `pytest tests/integration/test_e2e_smoke.py::test_local_session_lifecycle_to_websocket -q` (1 passed)
- `telec sync --validate-only` exited `0` with pre-existing documentation warnings.
- Verified six skill artifacts exist in `agents/skills/*` and under `~/.claude/skills`, `~/.codex/skills`, `~/.gemini/skills`.

## Fixes Applied

- Issue: Scope drift beyond approved requirements and plan.
  Fix: Re-scoped this todo in requirements and implementation plan to explicitly include the branch's CLI/runtime/install/test/doc alignment surfaces.
  Commit: `43522c8e`
- Issue: Invite fallback duplicates link output in non-JSON flows.
  Fix: Set `suppress_stdout_fallback=True` in `telec config invite` so fallback links are printed by one layer only; added unit test asserting single link print.
  Commit: `ee89fea2`
- Issue: `telec todo demo` behavior has partial test coverage.
  Fix: Added unit tests for `create` mode and parser compatibility with mode keywords plus `--project-root` ordering.
  Commit: `1cc4a506`

## Verdict

REQUEST CHANGES
