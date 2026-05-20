---
id: 'project/spec/feature/config/experiment-matching'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Config.is_experiment_enabled matches a named experiment with strict agent constraints, optimistic adapter constraints, and OR semantics across duplicate-named entries.'
---

# Experiment Matching — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

`Config.experiments` is a list of `ExperimentConfig` entries declaring which
feature-flag experiments are active, optionally narrowed by agent and/or
adapter dimensions. Callers ask `config.is_experiment_enabled(name, agent=…,
adapter=…)` to check whether an experiment applies in a given context. The
resolver has three behavioral pillars: multiple entries with the same `name`
are OR'd together (any match wins), the agent dimension is **strict** (when
an entry constrains agents, the caller must supply a matching agent), and
the adapter dimension is **optimistic** (when the caller omits an adapter,
adapter constraints on entries are ignored — useful when a coordinator asks
"does ANY adapter want this experiment?"). Entries are parsed from
`config.yml:experiments` and any sibling `experiments.yml` side-file, with
the side-file appending to the primary list.

## Canonical fields

### Use cases

#### UC-CFG-EXP-1: Unconstrained entry matches any agent and adapter

```
Given Config.experiments contains one entry:
  ExperimentConfig(name="feature_x", agents=None, adapters=None)
When a caller invokes config.is_experiment_enabled("feature_x")
Then the loop visits the entry
And the agent dimension is unconstrained (exp.agents is falsy)
And the adapter dimension is unconstrained (exp.adapters is falsy)
And the method returns True
And the same call returns True with any agent= and/or adapter= kwargs
```

#### UC-CFG-EXP-2: Agent dimension is strict

```
Given Config.experiments contains:
  ExperimentConfig(name="feature_x", agents=["gemini"], adapters=None)
When a caller invokes config.is_experiment_enabled("feature_x", agent="gemini")
Then the entry matches and the method returns True
When the same caller invokes config.is_experiment_enabled("feature_x", agent="claude")
Then the entry's agents list does not contain "claude" and the entry is skipped
And the method returns False
When the same caller invokes config.is_experiment_enabled("feature_x")  # no agent kwarg
Then `agent` is None and `agent not in exp.agents` is treated as a non-match
And the entry is skipped, the method returns False
```

#### UC-CFG-EXP-3: Adapter dimension is optimistic when caller omits adapter

```
Given Config.experiments contains:
  ExperimentConfig(name="feature_x", agents=None, adapters=["discord"])
When a caller invokes config.is_experiment_enabled("feature_x", adapter="discord")
Then the adapter matches and the method returns True
When the same caller invokes config.is_experiment_enabled("feature_x", adapter="telegram")
Then exp.adapters is truthy AND adapter is provided AND adapter not in exp.adapters
And the entry is skipped, the method returns False
When the same caller invokes config.is_experiment_enabled("feature_x")  # no adapter kwarg
Then the `adapter` arg is None, so the adapter dimension check is skipped
And the method returns True (optimistic: coordinator asking "does any adapter want this?")
```

#### UC-CFG-EXP-4: Same-name entries are OR'd

```
Given Config.experiments contains:
  ExperimentConfig(name="feature_x", agents=["claude"], adapters=None)
  ExperimentConfig(name="feature_x", agents=["gemini"], adapters=None)
When a caller invokes config.is_experiment_enabled("feature_x", agent="gemini")
Then the first entry's agents list does not contain "gemini" — skipped
And the second entry's agents list contains "gemini" — matches
And the method returns True
```

#### UC-CFG-EXP-5: Within an entry, dimensions AND

```
Given Config.experiments contains:
  ExperimentConfig(name="feature_x", agents=["claude"], adapters=["discord"])
When a caller invokes config.is_experiment_enabled("feature_x", agent="claude", adapter="discord")
Then both dimensions match and the method returns True
When the same caller invokes config.is_experiment_enabled("feature_x", agent="claude", adapter="telegram")
Then the agent matches but the adapter does not and the entry is skipped
And no other entry matches the name, so the method returns False
```

#### UC-CFG-EXP-6: Unknown experiment name returns False

```
Given Config.experiments contains entries only for "feature_x" and "feature_y"
When a caller invokes config.is_experiment_enabled("feature_z")
Then the loop visits no entries with matching name
And the method returns False without raising
```

#### UC-CFG-EXP-7: experiments.yml side-file appends to the experiments list

```
Given config.yml contains experiments: [ {name: "feature_x", agents: ["claude"]} ]
And the sibling experiments.yml contains experiments: [ {name: "feature_y"} ]
When teleclaude.config imports
Then expand_env_vars runs over both files
And the experiments.yml list extends _user_config["experiments"]
And _build_config parses the combined list into Config.experiments
And both feature_x and feature_y become queryable via is_experiment_enabled
```

### Implementation pointers (v1)

- `teleclaude/config/__init__.py:289-303` — `ExperimentConfig` dataclass (`name`, `agents`, `adapters` — both list dimensions default to `None`).
- `teleclaude/config/__init__.py:350-378` — `Config.is_experiment_enabled` resolution loop (skip-on-name-mismatch, strict agent dimension, optimistic adapter dimension).
- `teleclaude/config/__init__.py:781-791` — `_build_config` parse path for `experiments` raw list (per-entry dict → `ExperimentConfig`, falsy lists collapse to `None`).
- `teleclaude/config/__init__.py:347` — `Config.experiments` field default (`list[ExperimentConfig] = field(default_factory=list)`).
- `teleclaude/config/__init__.py:969-986` — module-level `experiments.yml` side-file merge into `_user_config["experiments"]` before final `_deep_merge` and `_build_config`.
- `teleclaude/daemon.py:259-261` — sample consumer: daemon logs the count of loaded experiments on startup.

### Cross-context references

- v1 does NOT emit any event when experiment matching toggles or when
  `experiments.yml` changes — there is no watcher. Consumers query
  `is_experiment_enabled` synchronously per use site.
- Consumed wherever feature gating exists. Sample caller pattern:
  `if config.is_experiment_enabled("feature_x", agent=agent_name): …`.
- The v2 `config` bounded context (see `docs/project/spec/domain/config.md`)
  folds experiments into the effective configuration aggregate and will
  emit `config.effective.updated` when the experiments overlay changes —
  not implemented in v1.

## Allowed values

- `name`: any string. No validation, no allow-list.
- `agents`: omitted/`null`/empty-list ⇒ unconstrained; otherwise a list of
  agent keys matched literally against the caller's `agent` kwarg
  (case-sensitive).
- `adapters`: omitted/`null`/empty-list ⇒ unconstrained; otherwise a list
  of adapter keys matched literally against the caller's `adapter` kwarg
  (case-sensitive).

## Known caveats

- **The two dimensions are not symmetric.** Agents are strict (`None` agent
  loses against a constrained entry); adapters are optimistic (`None`
  adapter wins against a constrained entry). The asymmetry is intentional
  — coordinators routinely ask "is this experiment on for ANY adapter?"
  without specifying one, and that question should return True when an
  entry exists for some adapter. Callers must understand which kwarg they
  may safely omit.
- **Falsy lists collapse to `None` at parse time.** `_build_config` does
  `list(exp_data["agents"]) if exp_data.get("agents") else None` — an
  empty list `[]` in YAML becomes `None`, meaning "unconstrained". This is
  a load-time normalisation; downstream code never sees an empty
  `agents=[]` entry.
- **No validation that agent/adapter values are known.** A typo like
  `agents: [gemnini]` parses successfully and silently never matches any
  real caller. `is_experiment_enabled` has no allow-list and no warning.
- **`adapters` constraints are silently ignored on coordinator-style
  calls.** A caller that omits `adapter=` cannot scope down via the
  adapter dimension; they can only widen. If a caller needs strict adapter
  enforcement they must always pass `adapter=`.
- **Same-name entries cannot subtract.** Because the loop returns True on
  the first match, there is no way to encode "enabled for claude EXCEPT
  on discord" with the current schema. Authors compose by adding
  permissive entries, never by suppressing them.
- **`experiments.yml` requires the top-level `experiments:` key.** A
  side-file whose entries live under a different root key is silently
  ignored (the merge only inspects `experiments`).
- **No precedence between `config.yml` and `experiments.yml`.** The
  side-file's list is appended to the primary list. With OR semantics
  across same-name entries, that means experiments in either file can
  enable a feature, but neither can disable an entry declared in the
  other.
