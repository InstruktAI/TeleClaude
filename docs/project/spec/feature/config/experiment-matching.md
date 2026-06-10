---
description: 'The experiment resolver matches a named experiment with strict agent constraints, optimistic adapter constraints, and OR semantics across duplicate-named entries.'
visibility: 'public'
---

# Experiment Matching — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The configured experiments are a list of entries declaring which
feature-flag experiments are active, optionally narrowed by agent and/or
adapter dimensions. Callers query the experiment resolver by name, with optional
agent and adapter arguments, to check whether an experiment applies in a given
context. The
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
Given the configured experiments contain one entry:
  {name: "feature_x"}  (no agent or adapter constraint)
When the experiment resolver is queried for "feature_x"
Then the loop visits the entry
And the agent dimension is unconstrained (the entry sets no agents)
And the adapter dimension is unconstrained (the entry sets no adapters)
And the resolver returns True
And the same query returns True with any agent= and/or adapter= arguments
```

#### UC-CFG-EXP-2: Agent dimension is strict

```
Given the configured experiments contain:
  {name: "feature_x", agents: ["gemini"]}
When the experiment resolver is queried for "feature_x" with agent="gemini"
Then the entry matches and the resolver returns True
When the resolver is queried for "feature_x" with agent="claude"
Then the entry's agents list does not contain "claude" and the entry is skipped
And the resolver returns False
When the resolver is queried for "feature_x" with no agent argument
Then no agent was supplied, and a constrained-agents entry treats the missing agent as a non-match
And the entry is skipped, the resolver returns False
```

#### UC-CFG-EXP-3: Adapter dimension is optimistic when caller omits adapter

```
Given the configured experiments contain:
  {name: "feature_x", adapters: ["discord"]}
When the experiment resolver is queried for "feature_x" with adapter="discord"
Then the adapter matches and the resolver returns True
When the resolver is queried for "feature_x" with adapter="telegram"
Then the entry constrains adapters, an adapter was provided, and it is not in the entry's adapter list
And the entry is skipped, the resolver returns False
When the resolver is queried for "feature_x" with no adapter argument
Then the adapter dimension check is skipped
And the resolver returns True (optimistic: coordinator asking "does any adapter want this?")
```

#### UC-CFG-EXP-4: Same-name entries are OR'd

```
Given the configured experiments contain:
  {name: "feature_x", agents: ["claude"]}
  {name: "feature_x", agents: ["gemini"]}
When the experiment resolver is queried for "feature_x" with agent="gemini"
Then the first entry's agents list does not contain "gemini" — skipped
And the second entry's agents list contains "gemini" — matches
And the resolver returns True
```

#### UC-CFG-EXP-5: Within an entry, dimensions AND

```
Given the configured experiments contain:
  {name: "feature_x", agents: ["claude"], adapters: ["discord"]}
When the experiment resolver is queried for "feature_x" with agent="claude" and adapter="discord"
Then both dimensions match and the resolver returns True
When the resolver is queried for "feature_x" with agent="claude" and adapter="telegram"
Then the agent matches but the adapter does not and the entry is skipped
And no other entry matches the name, so the resolver returns False
```

#### UC-CFG-EXP-6: Unknown experiment name returns False

```
Given the configured experiments contain entries only for "feature_x" and "feature_y"
When the experiment resolver is queried for "feature_z"
Then the loop visits no entries with matching name
And the resolver returns False without raising
```

#### UC-CFG-EXP-7: experiments.yml side-file appends to the experiments list

```
Given config.yml contains experiments: [ {name: "feature_x", agents: ["claude"]} ]
And the sibling experiments.yml contains experiments: [ {name: "feature_y"} ]
When the config bounded context loads
Then env-var expansion runs over both files
And the experiments side-file list extends the primary experiments list
And the config build parses the combined list into the experiments registry
And both feature_x and feature_y become queryable via the experiment resolver
```

### Cross-context references

- No event is emitted today when experiment matching toggles or when
  `experiments.yml` changes. The config bounded context watches the
  experiments side-file and reloads edits into the live experiments list
  in-place; consumers query the resolver synchronously per use site.
- Consumed wherever feature gating exists. Sample query pattern: a
  capability queries the experiment resolver for "feature_x" with the
  current agent name before branching.
- The `config` bounded context (`project/spec/domain/config.md`) folds
  experiments into the effective configuration aggregate; a config event
  will eventually fire when the experiments overlay changes — that event
  is not emitted today.

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
- **Falsy lists collapse to `None` at parse time.** An empty agents list `[]`
  in YAML is normalised to `None` at load time, meaning "unconstrained". This
  happens because the config builder treats a falsy agents value as absent.
  Downstream code never sees an empty `agents=[]` entry.
- **No validation that agent/adapter values are known.** A typo like
  `agents: [gemnini]` parses successfully and silently never matches any
  real caller. The experiment resolver has no allow-list and no warning.
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
