# Requirements: Job Contract Refinements

## Goal

Tighten the job contract so agent-type jobs are doc-driven (not config-driven), job inputs are validated before execution, and `telec sync` catches broken job configs at commit time.

## Problem Statement

1. **Agent jobs carry inline instructions.** The `message` field in `teleclaude.yml` duplicates what should live in the spec doc. This creates drift — the config and the doc can disagree, and the config is untracked by doc validation.
2. **No job validation in `telec sync`.** Doc snippets and agent artifacts are validated at sync/commit time, but job configs are only parsed at runtime by the cron runner. Broken configs (missing fields, bad references) are silent until the job tries to run.
3. **Person config schema mismatch.** `discovery.py` expects `interests.tags` (nested mapping) but Morriz's config has `interests` as a flat list. Tags are always empty — the YouTube tagger silently does nothing.
4. **No input contract.** Jobs that require per-person data (CSV path, tags) have no way to declare their inputs. The runner can't validate that a subscriber has the required fields before dispatching.

## Changes

### 1. Replace `message` with `job` for agent-type jobs

Agent jobs in `teleclaude.yml` get a mandatory `job` field that references their spec doc. The `message` field is disallowed for agent-type jobs.

```yaml
# Before
memory_review:
  type: agent
  message: "You are running the memory review job. Read @docs/..."

# After
memory_review:
  type: agent
  job: memory_review  # resolves to docs/project/spec/jobs/memory-review.md
  agent: claude
  thinking_mode: fast
  schedule: weekly
  preferred_weekday: 0
  preferred_hour: 8
```

The runner constructs the agent prompt: `"Read @docs/project/spec/jobs/{job}.md and execute the job instructions."` — derived from the `job` field, not from freeform config.

### 2. Add job validation to `telec sync`

Add a `validate_jobs()` phase to the sync pipeline (alongside existing snippet/artifact validation):

- Every job entry in `teleclaude.yml` has valid schedule fields.
- Agent-type jobs have a `job` field pointing to an existing spec doc at `docs/project/spec/jobs/{job}.md`.
- Agent-type jobs do NOT have a `message` field.
- Python-type jobs have a corresponding module at `jobs/{name}.py`.

### 3. Fix discovery.py interests handling

`discovery.py` must accept both shapes:

- `interests: [list]` — flat list of tags (current person config format)
- `interests: { tags: [list] }` — nested mapping

This is a one-line fix: check `isinstance(interests, list)` before calling `_as_mapping()`.

### 4. Job input declarations (lightweight)

Add an optional `inputs` section to agent job spec docs that documents what per-person config fields are required. The validation phase can check that subscribers discovered for a job actually have the required fields.

For Python jobs, add a `required_subscriber_fields()` method to the `Job` base class (default: empty list). The runner checks before calling `run()`.

## Files

| File                                                                         | Change                                                                                |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `teleclaude/cron/runner.py`                                                  | Read `job` field, construct prompt from spec doc path, reject `message` on agent jobs |
| `teleclaude/cron/discovery.py`                                               | Handle flat list `interests` alongside nested `interests.tags`                        |
| `teleclaude/sync.py`                                                         | Call `validate_jobs()` in Phase 1                                                     |
| `teleclaude/resource_validation.py` (or new `teleclaude/jobs_validation.py`) | `validate_jobs()` function                                                            |
| `teleclaude.yml`                                                             | Replace `message` with `job` on `memory_review`                                       |
| `docs/project/spec/jobs/memory-review.md`                                    | No change (already has full instructions)                                             |
| `docs/project/design/architecture/jobs-runner.md`                            | Update agent-type fields table                                                        |
| `jobs/base.py`                                                               | Add `required_subscriber_fields()` with empty default                                 |

## Acceptance Criteria

1. Agent jobs use `job` field; `message` is rejected by validation.
2. `telec sync --validate-only` catches: missing spec docs, invalid schedule values, `message` on agent jobs, missing Python modules for python-type jobs.
3. `discovery.py` correctly returns tags for flat-list person configs.
4. Pre-commit hook blocks commits with broken job configs.
5. Existing 1024+ tests still pass.

## Explicit Non-Goals

- Per-person schedule overrides (future work, not needed until multiple people exist).
- Splitting `telec sync` into sub-commands (keep blanket approach, internally modular).
- OpenAPI-style schema for job inputs (too heavy — doc + method is enough).
