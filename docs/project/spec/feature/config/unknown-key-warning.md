---
id: project/spec/feature/config/unknown-key-warning
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Unknown keys in user-facing teleclaude.yml overlays are accepted (extra="allow") and surfaced as logger.warning entries via a recursive _warn_unknown_keys walk; the legacy machine config.yml applies hard rejection only to the agents block.
---

# Unknown Key Warning — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

Every Pydantic model in the user-facing `teleclaude.yml` schema declares
`model_config = ConfigDict(extra="allow")`. That setting tells Pydantic to
accept unknown keys silently into a `model_extra` bag rather than failing
validation. v1 layers a soft diagnostic on top: after `model_class.model_validate`
succeeds, `_warn_unknown_keys` walks the validated model recursively and
emits a `logger.warning` for each model node whose `model_extra` is
non-empty. The warning names the dotted path within the config tree, the
file the config was loaded from, and the unknown key names.

The recursion descends through three shapes:

- nested `BaseModel` instances reached via `__dict__` attribute access;
- `dict` values whose individual entries are `BaseModel` instances (e.g.,
  `agents` maps where each agent is its own model);
- `list` values whose individual elements are `BaseModel` instances (e.g.,
  the `people` list on `GlobalConfig`).

Behaviour is intentionally soft. Unknown keys do not stop the load and do
not invalidate any field. A typo in an overlay file passes validation,
contributes nothing to runtime behaviour, and shows up only in the daemon
log stream where an operator scanning warnings can spot it. The rationale is
forward-compatibility: a project pinned to an older release can declare keys
that a newer release will eventually consume; the older release ignores
them with a single warning rather than refusing to start.

The legacy machine `config.yml` follows a different rule because it does not
flow through Pydantic. Its `agents` block is the only sub-tree that gets
explicit unknown-key validation, and the policy there is HARD — unknown
agent keys raise `ValueError`, never warn. Every other top-level key in
`config.yml` accepts arbitrary dict shape because the legacy parser walks
typed fields explicitly and ignores anything it does not look for.

## Canonical fields

### Use cases

#### UC-CFG-UNKNOWN-1: Unknown top-level overlay key emits a single warning

```
Given /repos/my-project/teleclaude.yml contains the key `mystery_key: 42` at the top level
And `mystery_key` is not declared on ProjectConfig
When load_config(path, ProjectConfig) runs
Then model_validate succeeds because ProjectConfig has model_config = ConfigDict(extra="allow")
And the resulting model holds model_extra = {"mystery_key": 42}
And _warn_unknown_keys is invoked with path="root" and the config file path
And exactly one logger.warning is emitted with the shape:
  "Unknown keys in %s at %s: %s", path="root", config_path=<the file>, keys=["mystery_key"]
And the returned model is otherwise complete and usable
```

#### UC-CFG-UNKNOWN-2: Unknown key inside a nested BaseModel walks to that node's path

```
Given a teleclaude.yml that includes:
  business:
    domains: { primary: "instrukt.ai" }
    typo_field: "oops"
And BusinessConfig has model_config = ConfigDict(extra="allow") but no `typo_field`
When load_config runs and _warn_unknown_keys recurses into model.__dict__
Then the helper visits the BusinessConfig instance via the `business` attribute
And emits a logger.warning with path="root.business" listing ["typo_field"]
And no warning is emitted at path="root" (top-level model_extra is empty)
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
And `wizard` is not in the known_agents tuple consulted by _validate_known_agent_keys
When teleclaude/config/__init__.py module load runs
Then _require_agents_section confirms `agents:` is a mapping
And _validate_known_agent_keys raises ValueError with message:
  "Unknown key(s) under `config.yml:agents`: wizard. Allowed keys: <known>."
And module import fails — no warning path exists for this case
```

#### UC-CFG-UNKNOWN-6: Legacy config.yml: unknown non-agents top-level key is silently accepted

```
Given a config.yml whose top-level contains a key `someday_setting: {...}` that no _parse_* helper reads
And the key is not `agents` and is not on the disallowed-runtime list
When the module load reaches _build_config(_merged)
Then the unknown key contributes nothing to the resulting Config dataclass
And no warning, no error, no log entry mentions the unused key
And the daemon proceeds as if the key were absent
```

### Implementation pointers (v1)

- `teleclaude/config/loader.py:17-35` — `_warn_unknown_keys` recursive walk; checks `model.model_extra`, descends into nested `BaseModel` attributes, into dict values that are BaseModels, and into list items that are BaseModels.
- `teleclaude/config/loader.py:60` — `_warn_unknown_keys(model, "root", path)` invocation in `load_config` after `model_validate` succeeds.
- `teleclaude/config/schema.py` — every overlay model declares `model_config = ConfigDict(extra="allow")` (representative lines: 18, 25, 86, 108, 115, 121, 140, 150, 171, 180, 188, 195, 204, 212, 242, 252, 261, 270, 279, 288, 296, 311, 358, 401).
- `teleclaude/config/__init__.py:495-509` — `_validate_disallowed_runtime_keys` (hard rejection for `computer.tmux_binary`; unrelated to unknown-key warning policy but co-resident).
- `teleclaude/config/__init__.py:524-533` — `_validate_known_agent_keys` (HARD `ValueError` for unknown keys under `config.yml:agents`).

### Cross-context references

- The warnings flow through the daemon's standard `instrukt_ai_logging` stream;
  operators reviewing daemon logs (or the TUI's logs view) are the only
  consumers. There is no domain event emitted for unknown keys.
- The forward-compatibility intent is shared with the v2 `config` context
  (see `docs/project/spec/domain/config.md`), which flags that v2 may tighten
  unknown keys from "warning" to "error" once the migration window closes.

## Allowed values

- Any unknown key shape is permitted in v1 overlays; the warning only
  reports the keys, it never restricts them.
- For `config.yml:agents`, allowed agent keys are the tuple consulted by
  `_validate_known_agent_keys`; any other entry under `agents` raises.

## Known caveats

- **Warnings, not errors.** A misconfigured operator who relies on a typo'd
  key (e.g., `enabld: true` instead of `enabled: true`) will see no
  immediate failure — the default for the real field applies, and the
  warning is buried in logs. The first symptom may be unexpected runtime
  behaviour.
- **Recursion only walks declared field shapes.** The helper recognises
  three shapes: nested `BaseModel`, dict values that are `BaseModel`, and
  list items that are `BaseModel`. Unknown keys nested INSIDE `model_extra`
  itself (e.g., the operator dropped a whole subtree with unknown shape) are
  reported only at the topmost level where `model_extra` first appears; the
  helper does not crack open arbitrary dicts inside `model_extra`.
- **Two configuration surfaces, two policies.** The Pydantic overlay path
  warns; the legacy machine `config.yml` path raises for `agents` and
  silently drops everything else. Operators editing both files cannot rely
  on a single mental model for unknown-key behaviour.
- **`extra="allow"` is universal on overlay models.** Tightening unknown-key
  policy in v1 means flipping every `ConfigDict` declaration in
  `schema.py` — a coordinated change, not a per-model knob. The v2
  cutover is the planned moment for that flip.
- **No structured warning payload.** The warning is a `logger.warning` with
  positional format args; downstream filtering must parse strings. There is
  no event taxonomy entry for unknown-key occurrences.
