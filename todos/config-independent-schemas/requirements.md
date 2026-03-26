# Requirements: config-independent-schemas

## Goal

Eliminate crashes when CLI commands run from non-project workspaces (e.g. person
directories under `~/.teleclaude/people/`) by making each configuration schema
independent and composing them at the entry point instead of relying on
inheritance between config levels.

## Root Cause

Interior functions in the docs/context pipeline call `load_project_config()` on
whatever `teleclaude.yml` exists at `cwd`. When `cwd` is a person workspace,
that file is a PersonConfig containing keys (`creds`, `notifications`) that
ProjectConfig's validator rejects. The crash is a validation error, not a missing
file.

## Scope

### In scope

1. **Independent config schemas** — GlobalConfig must not inherit from
   ProjectConfig. Each config level (global, project, person) must be a
   standalone schema that validates only its own fields and rejects keys
   belonging to other levels.

2. **Composed application config** — A single composed type that holds the
   validated layers (global always present; project and person optional). This
   type is constructed from pre-validated parts, not validated itself.

3. **Entry-point config loading** — A single loader function that determines the
   workspace type (person workspace vs. project workspace), loads the
   appropriate layers, and returns the composed config. No fallback for
   unrecognized paths — the loader must not guess. [inferred]

4. **Eliminate interior config loading from the docs/context pipeline** — The
   functions that resolve project domains and project name must receive config
   data as parameters instead of loading config internally. The docs CLI handler
   must call the entry-point loader and pass config through.

5. **Relocate checkout_root** — `checkout_root` is a system-wide setting that
   belongs at the global config level, not inside a project-scoped sub-model.
   The git helper that reads `checkout_root` must read it from the global layer.

6. **Atomic project config writes** — A save function for project-level config
   must exist, following the same atomic write pattern already used for global
   and person configs. Scattered direct writes to project config files must
   route through it. [inferred]

7. **Test updates** — All existing tests affected by the schema and loader
   changes must be updated. New tests must cover the composed config loader,
   workspace detection, and the crash scenario.

### Out of scope

- Changing config file format or location on disk.
- Migrating existing config files (the YAML shape is unchanged per level).
- Refactoring callers outside the docs/context pipeline (cron runner, daemon
  event platform, deployment handler, sync, etc.) unless they break from the
  schema change. [inferred]
- Config wizard changes (no new config surface is introduced).

### Scope addendum — incidental bug fixes in branch

Two small bug fixes were discovered and applied during implementation of this work item.
They are unrelated to config schema independence but were included to avoid losing the
context-local fixes:

1. **`teleclaude/core/identity.py`** — `return IdentityContext()` changed to
   `return IdentityContext(person_role=HUMAN_ROLE_CUSTOMER)` to default unresolved
   terminal-origin identity to the customer role instead of an empty identity.

2. **`teleclaude/utils/transcript/_parsers.py`** — `_extract_codex_reasoning_text` now
   includes string-typed summary items (previously only dict-typed items were emitted);
   corresponding test updated. This fixes incomplete Codex reasoning display.

Both fixes have test coverage and no scope impact on the config-independence goal.

## Success Criteria

- [ ] Running `telec docs index` from a person workspace (e.g.
      `~/.teleclaude/people/<name>/`) returns global snippets without crashing.
- [ ] Running `telec docs index` from a project workspace works as before
      (returns project + global snippets).
- [ ] `telec config validate` passes at all levels (global, project, person).
- [ ] GlobalConfig and ProjectConfig share no inheritance relationship.
- [ ] The composed config type correctly represents the optionality of each
      layer (global always present; project and person may be absent).
- [ ] No function in the docs/context pipeline calls a config loader internally;
      config flows from the entry point.
- [ ] `checkout_root` is read from the global config layer; the project-level
      sub-model no longer owns it.
- [ ] Atomic project config writes use the same pattern as global/person saves.
- [ ] Pre-commit hooks pass (tests, lint, typecheck).
- [ ] No regressions in existing config validation behavior for any level.

## Constraints

- The YAML file structure for each config level must remain backward-compatible.
  Existing `teleclaude.yml` files must load without modification.
- The `reject_disallowed_keys` validators on each schema must continue to
  enforce level-specific key restrictions.
- The composed config type must be immutable after construction. [inferred]
- `checkout_root` must continue to work when set in existing global configs
  (the field moves in the schema, but the YAML key path may change). If the
  YAML key path changes, the old path must still be accepted during a
  transition period. [inferred]

## Risks

- **Callers outside scope that depend on GlobalConfig inheriting ProjectConfig
  fields** — Breaking the inheritance means GlobalConfig no longer has
  `project_name`, `business`, `hooks`, `jobs`, `git`, `integrator`,
  `channel_subscriptions`, or `deployment`. Any code that reads these fields
  from a GlobalConfig instance will break. The builder must verify all
  GlobalConfig consumers. [inferred]
- **checkout_root migration** — Moving `checkout_root` from `git.checkout_root`
  to a top-level global field changes the YAML path. Existing configs with
  `git.checkout_root` must continue to work.

## Verification

1. **Crash scenario**: `cd ~/.teleclaude/people/<name> && telec docs index` —
   must return global snippets, no crash.
2. **Normal scenario**: `cd <project-root> && telec docs index` — must return
   project + global snippets as before.
3. **Config validation**: `telec config validate` — all levels pass.
4. **Pre-commit**: tests, lint, typecheck all green.
