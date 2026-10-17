---
description: 'Each user-facing config level rejects keys that belong to another level, preventing silent misplacement across project, global, person, and machine config.'
visibility: 'public'
---

# Per-Level Key Restriction — Spec

## Required reads

- @docs/local/spec/domain/config.md

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

#### UC-CFG-KEYREJECT-2: Project file rejects multiple misplaced keys

#### UC-CFG-KEYREJECT-3: Global file rejects `creds`

#### UC-CFG-KEYREJECT-4: Global file accepts allowed keys

#### UC-CFG-KEYREJECT-5: Person file rejects `business`

#### UC-CFG-KEYREJECT-6: Legacy config.yml rejects computer.tmux_binary

#### UC-CFG-KEYREJECT-7: Legacy config.yml accepts a clean computer block

#### UC-CFG-KEYREJECT-8: Non-dict input short-circuits silently

### Cross-context references

- **Bound to the layered-overlay-resolution feature** — these validators
  run inside the project, global, and per-person overlay load entry
  points. See `local/projects/teleclaude/spec/feature/config/layered-overlay-resolution.md`.
- **Machine `config.yml` runtime check** — invoked by the machine config
  loader; the `config` domain spec describes the runtime configuration
  aggregate that carries this contract. The disallowed-runtime-keys check
  is the enforcement seam.
- **Ubiquitous-language alignment** — the layer names (global / project /
  person) and the per-layer ownership of `creds`, `business`, `people`,
  etc. match the overlay definitions in `local/projects/teleclaude/spec/domain/config.md`.

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
