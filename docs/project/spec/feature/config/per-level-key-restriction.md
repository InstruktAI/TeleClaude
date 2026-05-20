---
id: 'project/spec/feature/config/per-level-key-restriction'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Each user-facing config level rejects keys that belong to another level, preventing silent misplacement across project, global, person, and legacy machine config.'
---

# Per-Level Key Restriction — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Each layer of the user-facing configuration surface owns a fixed set of keys.
v1 enforces this ownership by REJECTING keys that belong to another layer when
they appear in the wrong file. Without this check, a misplaced key would load
silently as part of `extra="allow"` and have no effect — the consumer reading
the correct layer would never see the value. The validators turn this
silent-misplacement failure mode into a hard load-time error that names the
offending keys.

Three Pydantic `model_validator(mode="before")` hooks enforce the rule on the
three `teleclaude.yml` overlay levels:

- `ProjectConfig` rejects `people`, `ops`, `creds`, `notifications`, `timezone`.
- `GlobalConfig` rejects `creds`, `notifications`, `timezone`.
- `PersonConfig` rejects `people`, `ops`, `business`, `timezone`.

A fourth check guards the legacy machine `config.yml` (not a `teleclaude.yml`
overlay). `_validate_disallowed_runtime_keys` rejects `computer.tmux_binary`
because that field is now hardcoded runtime policy and is no longer
user-configurable.

Each check fires before Pydantic's normal field parsing, so a misplaced key
prevents the entire layer from loading rather than landing in `extra`.

## Canonical fields

### Use cases

#### UC-CFG-KEYREJECT-1: Project file rejects `people`

```
Given a project teleclaude.yml that contains a top-level `people:` list
When load_project_config parses the file via ProjectConfig
Then ProjectConfig.reject_disallowed_keys (model_validator mode="before") runs
And disallowed = {"people", "ops", "creds", "notifications", "timezone"}
And present = {"people"}
And ValueError is raised with message "Keys not allowed at project level: people"
And Pydantic surfaces the validation failure
And load_project_config raises before AppConfig is composed
```

#### UC-CFG-KEYREJECT-2: Project file rejects multiple misplaced keys

```
Given a project teleclaude.yml that contains both `creds:` and `notifications:`
When ProjectConfig.reject_disallowed_keys runs
Then present = {"creds", "notifications"}
And ValueError is raised with message naming both keys, comma-separated
And the project does not load
```

#### UC-CFG-KEYREJECT-3: Global file rejects `creds`

```
Given ~/.teleclaude/teleclaude.yml that contains a top-level `creds:` block
When load_global_config parses the file via GlobalConfig
Then GlobalConfig.reject_disallowed_keys runs
And disallowed = {"creds", "notifications", "timezone"}
And present = {"creds"}
And ValueError is raised with message "Keys not allowed at global level: creds"
And the global layer does not load
```

#### UC-CFG-KEYREJECT-4: Global file accepts allowed keys

```
Given ~/.teleclaude/teleclaude.yml that contains only `people:`, `subscriptions:`, `interests:`
When GlobalConfig.reject_disallowed_keys runs
Then disallowed.intersection(data.keys()) is empty
And the validator returns data unchanged
And GlobalConfig populates normally
```

#### UC-CFG-KEYREJECT-5: Person file rejects `business`

```
Given ~/.teleclaude/people/alice/teleclaude.yml that contains a `business:` block
When load_person_config parses the file via PersonConfig
Then PersonConfig.reject_disallowed_keys runs
And disallowed = {"people", "ops", "business", "timezone"}
And present = {"business"}
And ValueError is raised with message "Keys not allowed at per-person level: business"
And the person layer does not load
```

#### UC-CFG-KEYREJECT-6: Legacy config.yml rejects computer.tmux_binary

```
Given a machine config.yml whose `computer:` mapping contains a `tmux_binary:` key
When the loader runs _validate_disallowed_runtime_keys(user_config)
Then disallowed.append("computer.tmux_binary") fires
And ValueError is raised with message:
  "config.yml contains disallowed runtime keys: computer.tmux_binary.
   Agent and tmux binaries are now hardcoded runtime policy and cannot be configured."
And the machine config does not load
```

#### UC-CFG-KEYREJECT-7: Legacy config.yml accepts a clean computer block

```
Given a machine config.yml whose `computer:` mapping contains only allowed keys (no tmux_binary)
When _validate_disallowed_runtime_keys(user_config) runs
Then disallowed remains an empty list
And the function returns without raising
And the legacy config loads normally
```

#### UC-CFG-KEYREJECT-8: Non-dict input short-circuits silently

```
Given a YAML file whose top-level node is a scalar or list (not a mapping)
When ProjectConfig.reject_disallowed_keys / GlobalConfig.reject_disallowed_keys / PersonConfig.reject_disallowed_keys receives data
Then isinstance(data, dict) is False
And the validator returns data unchanged
And subsequent Pydantic parsing produces its own type error against the actual schema
```

### Implementation pointers (v1)

- `teleclaude/config/schema.py:342-352` — `ProjectConfig.reject_disallowed_keys` (rejects `people`, `ops`, `creds`, `notifications`, `timezone`).
- `teleclaude/config/schema.py:385-395` — `GlobalConfig.reject_disallowed_keys` (rejects `creds`, `notifications`, `timezone`).
- `teleclaude/config/schema.py:415-425` — `PersonConfig.reject_disallowed_keys` (rejects `people`, `ops`, `business`, `timezone`).
- `teleclaude/config/__init__.py:495-510` — `_validate_disallowed_runtime_keys` (rejects `computer.tmux_binary` in the legacy `config.yml`).

### Cross-context references

- **Bound to the layered-overlay-resolution feature** — these validators run inside the `load_project_config`, `load_global_config`, and `load_person_config` entry points. See `docs/project/spec/feature/config/layered-overlay-resolution.md`.
- **`config.yml` runtime check** — invoked by the legacy machine config loader; the v2 `config` domain spec describes the runtime configuration aggregate that replaces this path. Until v2 cutover, `_validate_disallowed_runtime_keys` is the enforcement seam.
- **Ubiquitous-language alignment** — the layer names (global / project / person) and the per-layer ownership of `creds`, `business`, `people`, etc. match the overlay definitions in `docs/project/spec/domain/config.md`.

## Allowed values

Per-layer forbidden sets (any presence triggers rejection):

| Layer / file                                                  | Forbidden top-level keys                              |
| ------------------------------------------------------------- | ----------------------------------------------------- |
| `ProjectConfig` (`<project>/teleclaude.yml`)                  | `people`, `ops`, `creds`, `notifications`, `timezone` |
| `GlobalConfig` (`~/.teleclaude/teleclaude.yml`)               | `creds`, `notifications`, `timezone`                  |
| `PersonConfig` (`~/.teleclaude/people/<name>/teleclaude.yml`) | `people`, `ops`, `business`, `timezone`               |
| Legacy `config.yml` (runtime)                                 | `computer.tmux_binary`                                |

Error message shapes:

- Pydantic levels: `"Keys not allowed at <project|global|per-person> level: <comma-joined-keys>"`.
- Legacy `config.yml`: `"config.yml contains disallowed runtime keys: <comma-joined>. Agent and tmux binaries are now hardcoded runtime policy and cannot be configured."`.

## Known caveats

- **`model_config = ConfigDict(extra="allow")` is still set on every level.**
  The per-level validator is the _only_ thing standing between a misplaced
  key and silent acceptance into the model's `__pydantic_extra__`. Removing
  or short-circuiting the validator would re-enable silent misplacement.
- **Asymmetric forbidden sets are intentional.** `business` is forbidden on
  the person level but allowed on the project level; `people` is forbidden on
  both the project and person levels but is the central object of the global
  level. The sets reflect which layer owns each concept; they are not
  derivable from a single "everything except mine" rule.
- **Order is set-based, not preserved.** When multiple forbidden keys are
  present, the error message orders them via Python set iteration; the order
  is not stable across runs. Tests asserting on the error message should
  match on key presence, not order.
- **The runtime-key check only covers `computer.tmux_binary` today.** The
  `disallowed` list in `_validate_disallowed_runtime_keys` is an explicit
  registry, not a general scheme. New runtime-policy fields that need to be
  rejected must be added explicitly.
- **Non-dict YAML inputs slip through this guard.** A YAML file whose root is
  a list or scalar passes the `isinstance(data, dict)` check at False and is
  returned unchanged; the subsequent Pydantic parsing then raises its own
  type error. The per-level rejection is a precondition layered on top of
  Pydantic's normal validation, not a replacement for it.
- **No drift detection.** If a new layer-owned key (e.g., a new
  `PersonConfig` field) is added without updating the _other_ layers'
  `disallowed` sets to include it, the new key is silently accepted on the
  wrong layer. Maintenance discipline is required — the forbidden sets are
  hand-maintained.
