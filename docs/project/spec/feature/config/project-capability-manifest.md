---
description: 'Per-project capability manifest in teleclaude.yml: explicit enabled toggles for todos, code, docs, and agents; derived checkpoint activation; convergent plumbing.'
visibility: 'internal'
delivered_by:
  - project-capability-manifest
---

# Project Capability Manifest — Spec

## What it is

`teleclaude.yml` declares which platform capabilities a project subscribes to.
Capabilities are explicit in config; inference happens only at analyze-time
(`telec projects analyze` / `assess` inspects the repo and writes the toggles).
No runtime code path infers a capability from repo shape. The checkpoint
engine's activation is derived from the subscribed capabilities — there is no
independent on/off flag for the engine itself.

## Canonical fields

- `todos: { enabled }` — task tracking (`telec todo`, `telec bugs`). Defaults
  to `true` wherever a `teleclaude.yml` exists; a data repository carries a
  manifest for exactly this capability.
- `code: { enabled }` — the project holds code under the TeleClaude lifecycle.
  Owns the sealed-commit surface (`telec code *`), quality lanes, git hooks,
  the tmux git wrapper, worktree rules, and the checkpoint toolchain and
  log-check bindings. `telec code *` refuses cleanly ("not a code project")
  when disabled.
- `docs: { enabled }` — the snippet pipeline: the `docs/** → telec sync` base
  binding and the `.gitattributes` docs filters.
- `agents: { enabled }` — agent artifacts: the `agents/**`-family base binding
  (`telec sync` + `telec sessions restart self`).

Derivation rules:

- The checkpoint engine evaluates a turn iff `code ∨ docs ∨ agents` is enabled
  or the project declares at least one custom binding. Otherwise `agent_stop`
  passes through with no timeline extraction and no evidence scanning.
- The commit obligation is active iff `code ∨ docs` is enabled.
- Dependent plumbing (git hooks, tmux git wrapper, `.gitattributes` filters)
  is derived state: an idempotent reconciler converges installed plumbing to
  the manifest at `telec projects init`, `telec sync`, re-assess, and a cheap
  session-start drift check. Disabling a capability removes its plumbing on
  the next convergence — installation is never a one-shot init event.
- Each `enabled` defaults to `true` for an already-onboarded project so
  existing repos keep today's behavior; analyze writes explicit values on the
  next assessment.

## Known caveats

- `ProjectConfig` parses unknown keys (`extra="allow"`): a manifest authored
  ahead of delivery parses harmlessly and becomes load-bearing at delivery.
- Capability toggles gate _mechanisms_, not content: disabling `docs` in a
  repo that still contains snippet frontmatter leaves those files unsynced and
  is surfaced as drift by `telec projects assess`.

## See Also

- docs/project/design/architecture/checkpoint-system.md
- docs/project/procedure/checkpoint-overlay-projection.md
- docs/project/spec/domain/config.md
