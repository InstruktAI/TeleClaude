---
description: 'The experiment resolver matches a named experiment with strict agent constraints, optimistic adapter constraints, and OR semantics across duplicate-named entries.'
visibility: 'public'
---

# Experiment Matching — Spec

## Required reads

- @docs/local/spec/domain/config.md

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

Within one entry, every supplied constrained dimension must match. If no entry
matches the queried name and context, the experiment is inactive and the
resolver returns false without raising. Reloading rebuilds the effective list
from the primary configuration and appended side-file entries, preserving both
sources.

### Use cases

#### UC-CFG-EXP-1: Unconstrained entry matches any agent and adapter

#### UC-CFG-EXP-2: Agent dimension is strict

#### UC-CFG-EXP-3: Adapter dimension is optimistic when caller omits adapter

#### UC-CFG-EXP-4: Same-name entries are OR'd

#### UC-CFG-EXP-5: Within an entry, dimensions AND

#### UC-CFG-EXP-6: Unknown experiment name returns False

#### UC-CFG-EXP-7: experiments.yml side-file appends to the experiments list

### Cross-context references

- No event is emitted today when experiment matching toggles or when
  `experiments.yml` changes. The config bounded context watches the
  experiments side-file and reloads edits into the live experiments list
  in-place; consumers query the resolver synchronously per use site.
- Consumed wherever feature gating exists. Sample query pattern: a
  capability queries the experiment resolver for "feature_x" with the
  current agent name before branching.
- The `config` bounded context (`local/projects/teleclaude/spec/domain/config.md`) folds
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
