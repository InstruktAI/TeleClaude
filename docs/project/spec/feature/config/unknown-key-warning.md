---
description: 'Unknown keys in user-facing `teleclaude.yml` overlays are accepted and surfaced as warnings via a recursive walk; the machine `config.yml` applies hard rejection only to the `agents` block.'
visibility: 'public'
---

# Unknown Key Warning — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Every overlay schema model in the user-facing `teleclaude.yml` schema is
configured to accept unknown keys silently into an extras bag rather than
failing validation. v1 layers a soft diagnostic on top: after the overlay schema validates the
config successfully, the unknown-key walker traverses the validated model
recursively and emits a `logger.warning` for each model node whose
the extras bag is non-empty. The warning names the dotted path within the config tree, the
file the config was loaded from, and the unknown key names.

The recursion descends through three shapes:

- nested schema models reached by walking their fields;
- `dict` values whose individual entries are schema models (e.g.,
  `agents` maps where each agent is its own model);
- `list` values whose individual elements are schema models (e.g.,
  the `people` list on the global overlay).

Behaviour is intentionally soft. Unknown keys do not stop the load and do
not invalidate any field. A typo in an overlay file passes validation,
contributes nothing to runtime behaviour, and shows up only in the runtime
log stream where an operator scanning warnings can spot it. The rationale is
forward-compatibility: a project pinned to an older release can declare keys
that a newer release will eventually consume; the older release ignores
them with a single warning rather than refusing to start.

The legacy machine `config.yml` follows a different rule because it does not
flow through schema validation. Its `agents` block is the only sub-tree that gets
explicit unknown-key validation, and the policy there is HARD — unknown
agent keys raise a validation error, never warn. Every other top-level key in
`config.yml` accepts arbitrary dict shape because the legacy parser walks
typed fields explicitly and ignores anything it does not look for.

## Canonical fields

### Use cases

#### UC-CFG-UNKNOWN-1: Unknown top-level overlay key emits a single warning

```
Given /repos/my-project/teleclaude.yml contains the key `mystery_key: 42` at the top level
And `mystery_key` is not declared on the project overlay schema
When the config loader runs for a project overlay
Then overlay schema validation succeeds because extra keys are allowed
And the resulting model holds an extras bag = {"mystery_key": 42}
And the unknown-key walker is invoked with path="root" and the config file path
And exactly one logger.warning is emitted with the shape:
  "Unknown keys in %s at %s: %s", path="root", config_path=<the file>, keys=["mystery_key"]
And the returned model is otherwise complete and usable
```

#### UC-CFG-UNKNOWN-2: Unknown key inside a nested schema model walks to that node's path

```
Given a teleclaude.yml that includes:
  business:
<!-- planned-change:per-domain-symlink-single-owner -->
    domains: { primary: "instrukt.ai" }
<!-- change:per-domain-symlink-single-owner -->
    publishes: ["software-development"]
<!-- /planned-change:per-domain-symlink-single-owner -->
    typo_field: "oops"
And the business overlay schema accepts unknown keys but has no `typo_field`
When the config loader runs and the unknown-key checker recurses into the config model's fields
Then the checker visits the business config node via the `business` attribute
And emits a logger.warning with path="root.business" listing ["typo_field"]
And no warning is emitted at path="root" (the top-level extras bag is empty)
```

#### UC-CFG-UNKNOWN-3: Unknown key in a dict-of-models walks per-key

```
Given a teleclaude.yml that includes:
  agents:
    claude: { enabled: true, mystery: "x" }
    gemini: { enabled: false }
And AgentDispatchConfig accepts extras
When _warn_unknown_keys reaches the agents dict
Then it iterates dict values, finds each AgentDispatchConfig instance, and recurses
And emits a logger.warning with path="root.agents.claude" listing ["mystery"]
And emits NO warning for path="root.agents.gemini" (no extras present)
```

#### UC-CFG-UNKNOWN-4: Unknown key in a list-of-models walks per-index

```
Given a teleclaude.yml that includes:
  people:
    - { name: "alice", email: "a@x", role: "admin", unknown_field: 1 }
    - { name: "bob", email: "b@x", role: "member" }
And PersonEntry accepts extras
When _warn_unknown_keys recurses into the people list
Then it iterates the list, finds each PersonEntry instance, and recurses
And emits a logger.warning with path="root.people[0]" listing ["unknown_field"]
And no warning is emitted for path="root.people[1]"
```

#### UC-CFG-UNKNOWN-5: Legacy config.yml: unknown agents key is a HARD error

```
Given a config.yml whose top-level `agents` block contains an entry `wizard:`
And `wizard` is not in the known-agent set
When the machine-config load runs
Then the agents-section presence/shape check confirms `agents:` is a mapping
And the known-agent-key check raises a validation error with message:
  "Unknown key(s) under `config.yml:agents`: wizard. Allowed keys: <known>."
And the load fails — no warning path exists for this case
```

#### UC-CFG-UNKNOWN-6: Legacy config.yml: unknown non-agents top-level key is silently accepted

```
Given a config.yml whose top-level contains a key `someday_setting: {...}` that no machine-config parser reads
And the key is not `agents` and is not on the disallowed-runtime list
When the machine-config load builds the runtime configuration aggregate
Then the unknown key contributes nothing to the resulting aggregate
And no warning, no error, no log entry mentions the unused key
And the runtime proceeds as if the key were absent
```

### Cross-context references

- Warnings flow through the runtime's standard logging stream; operators
  reviewing runtime logs (or the TUI's logs view) are the only
  consumers. There is no domain event emitted for unknown keys.
- The forward-compatibility intent is shared with the `config` bounded
  context (see `project/spec/domain/config.md`), which flags that the
  policy may tighten from "warning" to "error" once the migration window
  closes.

## Allowed values

- Any unknown key shape is permitted in v1 overlays; the warning only
  reports the keys, it never restricts them.
- For `config.yml:agents`, allowed agent keys are those enforced by agent-key validation; any other entry under `agents` raises.

## Known caveats

- **Warnings, not errors.** A misconfigured operator who relies on a typo'd
  key (e.g., `enabld: true` instead of `enabled: true`) will see no
  immediate failure — the default for the real field applies, and the
  warning is buried in logs. The first symptom may be unexpected runtime
  behaviour.
- **Recursion only walks declared field shapes.** The helper recognises
  three shapes: nested schema models, dict values that are schema models, and
  list items that are schema models. Unknown keys nested INSIDE the extras bag
  itself (e.g., the operator dropped a whole subtree with unknown shape) are
  reported only at the topmost level where the extras bag first appears; the
  helper does not crack open arbitrary dicts inside the extras bag.
- **Two configuration surfaces, two policies.** The schema-validation overlay path
  warns; the legacy machine `config.yml` path raises for `agents` and
  silently drops everything else. Operators editing both files cannot rely
  on a single mental model for unknown-key behaviour.
- **`extra="allow"` is universal on overlay models.** Tightening unknown-key
  policy in v1 means updating every overlay schema's extra-key setting
  — a coordinated change, not a per-model knob. The v2
  cutover is the planned moment for that flip.
- **No structured warning payload.** The warning is a `logger.warning` with
  positional format args; downstream filtering must parse strings. There is
  no event taxonomy entry for unknown-key occurrences.
