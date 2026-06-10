---
description: 'Each user-facing config level rejects keys that belong to another level, preventing silent misplacement across project, global, person, and machine config.'
visibility: 'public'
---

# Per-Level Key Restriction — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Each layer of the user-facing configuration surface owns a fixed set of keys.
The config bounded context enforces this ownership by REJECTING keys that belong
to another layer when they appear in the wrong file. Without this check, a
misplaced key would load silently and have no effect — the consumer reading the
correct layer would never see the value. The validators turn this
silent-misplacement failure mode into a hard load-time error that names the
offending keys.

Three before-validation hooks enforce the rule on the three `teleclaude.yml`
overlay levels:

- The project overlay rejects `people`, `ops`, `creds`, `notifications`, `timezone`.
- The global overlay rejects `creds`, `notifications`, `timezone`.
- The per-person overlay rejects `people`, `ops`, `business`, `timezone`.

A fourth check guards the legacy machine `config.yml` (not a `teleclaude.yml`
overlay). The disallowed-runtime-keys check rejects `computer.tmux_binary`
because that field is now hardcoded runtime policy and is no longer
user-configurable.

Each check fires before the overlay schema's normal field parsing, so a
misplaced key prevents the entire layer from loading rather than being silently
accepted.

## Canonical fields

### Use cases

#### UC-CFG-KEYREJECT-1: Project file rejects `people`

```
Given a project teleclaude.yml that contains a top-level `people:` list
When the project overlay loader parses the file
Then the project overlay's before-validation restriction check runs
And the disallowed set for the project level is {"people", "ops", "creds", "notifications", "timezone"}
And the present disallowed keys are {"people"}
And a validation error is raised with message "Keys not allowed at project level: people"
And the project overlay does not load
```

#### UC-CFG-KEYREJECT-2: Project file rejects multiple misplaced keys

```
Given a project teleclaude.yml that contains both `creds:` and `notifications:`
When the project overlay's restriction check runs
Then the present disallowed keys are {"creds", "notifications"}
And a validation error is raised with a message naming both keys, comma-separated
And the project does not load
```

#### UC-CFG-KEYREJECT-3: Global file rejects `creds`

```
Given ~/.teleclaude/teleclaude.yml that contains a top-level `creds:` block
When the global overlay loader parses the file
Then the global overlay's restriction check runs
And the disallowed set for the global level is {"creds", "notifications", "timezone"}
And the present disallowed keys are {"creds"}
And a validation error is raised with message "Keys not allowed at global level: creds"
And the global layer does not load
```

#### UC-CFG-KEYREJECT-4: Global file accepts allowed keys

```
Given ~/.teleclaude/teleclaude.yml that contains only `people:`, `subscriptions:`, `interests:`
When the global overlay's restriction check runs
Then the disallowed and present sets have no intersection
And the validator passes the data through unchanged
And the global overlay loads normally
```

#### UC-CFG-KEYREJECT-5: Person file rejects `business`

```
Given ~/.teleclaude/people/alice/teleclaude.yml that contains a `business:` block
When the per-person overlay loader parses the file
Then the per-person overlay's restriction check runs
And the disallowed set for the person level is {"people", "ops", "business", "timezone"}
And the present disallowed keys are {"business"}
And a validation error is raised with message "Keys not allowed at per-person level: business"
And the person layer does not load
```

#### UC-CFG-KEYREJECT-6: Legacy config.yml rejects computer.tmux_binary

```
Given a machine config.yml whose `computer:` mapping contains a `tmux_binary:` key
When the loader runs the disallowed-runtime-keys check
Then the disallowed list includes "computer.tmux_binary"
And a validation error is raised with message:
  "config.yml contains disallowed runtime keys: computer.tmux_binary.
   Agent and tmux binaries are now hardcoded runtime policy and cannot be configured."
And the machine config does not load
```

#### UC-CFG-KEYREJECT-7: Legacy config.yml accepts a clean computer block

```
Given a machine config.yml whose `computer:` mapping contains only allowed keys (no tmux_binary)
When the disallowed-runtime-keys check runs
Then the disallowed list is empty
And the function returns without raising
And the legacy config loads normally
```

#### UC-CFG-KEYREJECT-8: Non-dict input short-circuits silently

```
Given a YAML file whose top-level node is a scalar or list (not a mapping)
When any overlay's restriction check receives the data
Then the input is detected as a non-dict
And the validator returns data unchanged
And subsequent schema parsing produces its own type error against the actual schema
```

### Cross-context references

- **Bound to the layered-overlay-resolution feature** — these validators
  run inside the project, global, and per-person overlay load entry
  points. See `project/spec/feature/config/layered-overlay-resolution.md`.
- **Machine `config.yml` runtime check** — invoked by the machine config
  loader; the `config` domain spec describes the runtime configuration
  aggregate that carries this contract. The disallowed-runtime-keys check
  is the enforcement seam.
- **Ubiquitous-language alignment** — the layer names (global / project /
  person) and the per-layer ownership of `creds`, `business`, `people`,
  etc. match the overlay definitions in `project/spec/domain/config.md`.

## Allowed values

Per-layer forbidden sets (any presence triggers rejection):

| Layer / file                                                      | Forbidden top-level keys                              |
| ----------------------------------------------------------------- | ----------------------------------------------------- |
| Project overlay (`<project>/teleclaude.yml`)                      | `people`, `ops`, `creds`, `notifications`, `timezone` |
| Global overlay (`~/.teleclaude/teleclaude.yml`)                   | `creds`, `notifications`, `timezone`                  |
| Per-person overlay (`~/.teleclaude/people/<name>/teleclaude.yml`) | `people`, `ops`, `business`, `timezone`               |
| Legacy `config.yml` (runtime)                                     | `computer.tmux_binary`                                |

Error message shapes:

- Overlay levels: `"Keys not allowed at <project|global|per-person> level: <comma-joined-keys>"`.
- Legacy `config.yml`: `"config.yml contains disallowed runtime keys: <comma-joined>. Agent and tmux binaries are now hardcoded runtime policy and cannot be configured."`.

## Known caveats

- **Extra-key acceptance is still configured on every overlay level.**
  The per-level restriction check is the _only_ thing standing between a
  misplaced key and silent acceptance into the overlay's extra-fields store.
  Removing or short-circuiting the check would re-enable silent misplacement.
- **Asymmetric forbidden sets are intentional.** `business` is forbidden on
  the person level but allowed on the project level; `people` is forbidden on
  both the project and person levels but is the central object of the global
  level. The sets reflect which layer owns each concept; they are not
  derivable from a single "everything except mine" rule.
- **Order is set-based, not preserved.** When multiple forbidden keys are
  present, the error message orders them via set iteration; the order
  is not stable across runs. Tests asserting on the error message should
  match on key presence, not order.
- **The runtime-key check only covers `computer.tmux_binary` today.** The
  disallowed list in the runtime-keys check is an explicit registry, not a
  general scheme. New runtime-policy fields that need to be rejected must be
  added explicitly.
- **Non-dict YAML inputs slip through this guard.** A YAML file whose root is
  a list or scalar passes the non-dict check and is returned unchanged; the
  subsequent schema parsing then raises its own type error. The per-level
  restriction is a precondition layered on top of the schema's normal
  validation, not a replacement for it.
- **No drift detection.** If a new layer-owned key is added without updating
  the _other_ layers' forbidden sets to include it, the new key is silently
  accepted on the wrong layer. Maintenance discipline is required — the
  forbidden sets are hand-maintained.
