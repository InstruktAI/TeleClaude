# Implementation Plan: config-wizard-governance

## Overview

Four governance doc edits, each adding targeted wording to close the config-surface blind spot. All changes are additive text within existing doc structures. No code changes.

## Phase 1: Core Changes

### Task 1.1: Add config-surface gate to Definition of Done

**File(s):** `docs/global/software-development/policy/definition-of-done.md`

- [x] In section "### 6. Documentation", add a new checklist item after the CLI help text item:
      `- [ ] If new configuration surface introduced (config keys, env vars, YAML sections): config wizard updated, config.sample.yml updated, teleclaude-config spec updated`

### Task 1.2: Strengthen DOR Gate 6 with config enumeration requirement

**File(s):** `docs/global/software-development/policy/definition-of-ready.md`

- [x] In Gate 6 "Dependencies & preconditions", add a new bullet:
      `- If the work introduces new configuration (config keys, env vars, YAML sections), they are listed explicitly and their wizard exposure is confirmed.`

### Task 1.3: Expand add-adapter procedure with registration steps

**File(s):** `docs/project/procedure/add-adapter.md`

- [x] Expand the Steps section from 5 to 9 steps. After existing step 3 ("Add configuration keys to `config.sample.yml`"), insert:
  - Step 4: Register adapter env vars in `_ADAPTER_ENV_VARS` (`teleclaude/cli/config_handlers.py`).
  - Step 5: Register field guidance in `GuidanceRegistry` (`teleclaude/cli/tui/config_components/guidance.py`).
  - Step 6: Verify config wizard discovers and exposes the new adapter area.
  - Step 7: Update teleclaude-config spec (`docs/project/spec/teleclaude-config.md`) with new config keys and env vars.
- [x] Renumber remaining steps (old 4→8, old 5→9).

### Task 1.4: Add maintenance note to teleclaude-config spec

**File(s):** `docs/project/spec/teleclaude-config.md`

- [ ] Add a "## Maintenance" section before "## Constraints" with the text:
      "This spec must be updated whenever config keys or env vars are added, renamed, or removed. The config wizard, `_ADAPTER_ENV_VARS` registry, and `GuidanceRegistry` must stay in sync with this spec."

---

## Phase 2: Validation

### Task 2.1: Sync and verify

- [ ] Run `telec sync` — must pass with no errors
- [ ] Verify all four edited files retain valid snippet frontmatter

### Task 2.2: Quality Checks

- [ ] Run `make lint` (if doc linting applies)
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm all six success criteria from requirements.md are addressed
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
