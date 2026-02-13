# Requirements: release-workflow-foundation

## Goal

Establish the baseline GitHub Actions infrastructure for TeleClaude, ensuring deterministic testing and a skeleton release workflow that triggers on every push to main.

## Success Criteria

- [ ] `lint-test.yaml` runs on every PR and push to main.
- [ ] `release.yaml` skeleton exists and triggers after `lint-test` on main.
- [ ] Workflow correctly handles `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` secrets (placeholder usage).

## Constraints

- Must use `uv` for dependency management in CI.
- Must run on `ubuntu-latest`.
