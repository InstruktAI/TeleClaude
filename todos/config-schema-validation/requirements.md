# Requirements: Config Schema Validation

## Goal

Introduce Pydantic-based schema validation for `teleclaude.yml` across all three configuration levels (project, global, per-person). Enforce level-specific constraints, validate before interpreting/merging, and fix existing schema mismatches.

## Problem Statement

`teleclaude.yml` is read by 6+ modules with ad-hoc `dict.get()` chains and no validation. This creates:

1. **Silent misconfiguration** — typos, wrong types, and invalid keys are silently ignored.
2. **Schema mismatch bugs** — `discovery.py` reads `interests.tags` (nested dict) but per-person config has a flat list of strings. Result: per-person subscribers silently get empty tags.
3. **No level enforcement** — nothing prevents a per-person config from declaring `people:` (which only the global level should do).
4. **Redundant config path** — `git_repo_helper.py` reads from `~/.teleclaude/config/teleclaude.yml` (a different path than the standard `~/.teleclaude/teleclaude.yml`).

## Config Levels

| Level          | Path                                         | Purpose                                                               |
| -------------- | -------------------------------------------- | --------------------------------------------------------------------- |
| **Project**    | `{repo}/teleclaude.yml`                      | Project-specific settings: `business.domains`, `jobs`, `project_name` |
| **Global**     | `~/.teleclaude/teleclaude.yml`               | Company-wide: `people`, `ops`, global `jobs`, global `subscriptions`  |
| **Per-person** | `~/.teleclaude/people/{name}/teleclaude.yml` | Individual: `creds`, `notifications`, `subscriptions`, `interests`    |

## Current Config Consumers

| Module                                      | Keys Read                                                        | Level                                                  |
| ------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------ |
| `context_selector.py`                       | `business.domains`                                               | Project                                                |
| `docs_index.py`                             | `project_name`, `business.domains`                               | Project                                                |
| `cron/runner.py`                            | `jobs.{name}.schedule`, `jobs.{name}.preferred_hour/weekday/day` | Project                                                |
| `cron/discovery.py`                         | `subscriptions.youtube`, `interests.tags`, `people`              | Global + Per-person                                    |
| `entrypoints/youtube_sync_subscriptions.py` | `people`, `subscriptions`, `creds`                               | Global + Per-person                                    |
| `helpers/git_repo_helper.py`                | `git.checkout_root`                                              | Redundant path (`~/.teleclaude/config/teleclaude.yml`) |
| `mcp/handlers.py`                           | Existence check only                                             | Project                                                |

## Schema Design

### Project-level schema

```yaml
project_name: str (optional)
business:
  domains:
    { domain-name }: { docs-path } # str → str mapping
jobs:
  { job-name }:
    when:
      every: str (optional, examples: "10m", "2h", "1d")
      at: str | list[str] (optional, "HH:MM" 24h format, system local time)
      weekdays: list[str] (optional with `at`; allowed: mon..sun)
    # legacy compatibility (to be supported during migration):
    schedule: hourly | daily | weekly | monthly
    preferred_hour: int (0-23, default 6)
    preferred_weekday: int (0-6, default 0)
    preferred_day: int (1-31, default 1)
git:
  checkout_root: str (optional)
```

### Scheduling semantics

1. New scheduling contract is `jobs.{name}.when`.
2. Exactly one of `when.every` or `when.at` is allowed.
3. `when.every` accepts minute/hour/day durations (`m|h|d`), minimum `1m`.
4. `when.at` accepts one or more `HH:MM` values in system local time.
5. `when.weekdays` is only valid with `when.at`.
6. Timezone is not configurable in schema; scheduler uses system local time.
7. Legacy schedule fields remain readable during migration but are deprecated.

### Global-level schema

Everything in project-level, plus:

```yaml
people:
  - name: str
    email: str
    username: str (optional)
    role: str (optional, default "member", allowed: admin|member|contributor|newcomer)
ops:
  - username: str
```

**Note:** `email` and `role` fields on PersonEntry are required by the downstream
`person-identity-auth` todo for identity resolution and role-based access control.

### Per-person schema

```yaml
creds:
  telegram:
    user_name: str
    user_id: int
notifications:
  telegram: bool
subscriptions:
  youtube: str # filename
interests: list[str] # flat list of tags
```

**Disallowed at per-person level:** `people`, `ops`.

## Level Constraints

1. Only the global config may declare `people` and `ops`.
2. Per-person configs must not contain `people`, `ops`, or `business`.
3. Project configs must not contain `people`, `ops`, `creds`, or `notifications`.
4. Unknown keys at any level should produce a warning (not a hard error) to allow forward compatibility.

## Bug Fixes Required

1. **Interests schema mismatch**: `discovery.py:76-77` calls `_as_mapping(cfg.get("interests"))` then `.get("tags")`. Per-person config has `interests: [list]` (flat). Fix: `discovery.py` must handle both `list[str]` (flat tags) and `dict` (nested with `.tags` key).
2. **Redundant config path**: `git_repo_helper.py:66` reads from `~/.teleclaude/config/teleclaude.yml`. Consolidate to the standard `~/.teleclaude/teleclaude.yml` or document the `config/` path as intentional.

## Acceptance Criteria

1. **Schema models**: Pydantic models for all three config levels with proper type constraints.
2. **Validation function**: `validate_config(path, level) -> Config | errors` that can be called by any consumer.
3. **Level enforcement**: Disallowed keys at each level produce clear validation errors.
4. **Consumer migration**: All 6+ config readers use the validated config object instead of raw `dict.get()`.
5. **Interests bug fixed**: Per-person subscribers get their tags correctly.
6. **Redundant path resolved**: Single canonical path per level, or documented justification.
7. **Unknown key warnings**: Forward-compatible — unknown keys warn, don't error.
8. **Tests**: Schema validation tests covering valid configs, invalid types, disallowed keys, and the interests mismatch.
9. **Scheduler compatibility**: `cron/runner.py` supports `when.every` and `when.at` without requiring cron expression strings.
10. **No timezone field**: Any timezone config key should be rejected as unknown/deprecated.

## Explicit Non-Goals

- No config merging across levels (each level is independent, read where needed).
- No migration tooling for existing configs (they already conform, just unvalidated).
- No GUI or interactive config editor.
- No runtime config reload / hot-reload.
