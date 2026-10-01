---
visibility: internal
description: Frozen v1 ownership anchor for file-based documentation, agent assets, deployment, and context selection.
---

# Context Domain Spec — Spec

## What it is

The v1 context area owns file-based documentation and agent assets, their
validation and deployment, and the selection of context supplied to agent
sessions. This repository carries only the current appliance contract;
replacement architecture is authoritative only in TeleClaudeNext.

## Canonical fields

- **Current behavior:** the documentation and agent-artifact policies plus
  feature specs that require this anchor.
- **Implementation roots:** `teleclaude/context_selector.py`,
  `teleclaude/docs/`, `teleclaude/resource_validation/`, and distribution code
  under `teleclaude/install/`.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. No replacement context architecture is
  authored here.

### Ownership boundary

- **Owns:** file-based documentation and agent-artifact validation,
  publication, deployment, and selection of context supplied to sessions.
- **Does not own:** the domain behavior described by published documents or the
  runtime decisions agents make after context is supplied.
- **Published contracts:** validated snippet and artifact packages, publication
  indexes, and context-selection results.

<!-- planned-change:subject-scope-reach -->
- **Also owns:** the resolved read scope — which documentation tiers a caller
  may reach, how deeply each is read, and the authorization of the selectors
  that name a tier explicitly. These are rules about documentation reach, so
  they resolve here rather than to the contexts that supply their inputs.
<!-- change:subject-scope-reach -->
- **Also owns:** the resolved read scope — which documentation tiers are
  assembled for a caller, how deeply each is read, and the authorization of the
  selectors that name a tier explicitly. Depth converts `identity`'s visibility
  reach (`local/projects/teleclaude/spec/domain/identity`): a tier it admits is read in
  full. Which tiers a caller may read in full is that reach, decided by
  `identity`; assembly, public-only depth, and the `public` and person-local
  audience facts are documentation rules and resolve here.
<!-- /planned-change:subject-scope-reach -->
- **Also does not own:** the relationships those rules read. Which person a call
  resolves to, which companies that person belongs to, and which projects they
  are assigned to are resolved facts belonging to `identity`; which company owns
  a project is a declaration belonging to `config`. This context consumes both
  through their published contracts and restates neither.

**Resolved read scope** — for one caller, the set of documentation tiers in
<!-- planned-change:subject-scope-reach -->
reach paired with the depth each is read at. Depth is one of two values: a tier
the caller holds a declared relationship to is read in full, and a tier they
hold none to is read at whatever its snippets declare about themselves. Depth is
<!-- change:subject-scope-reach -->
reach paired with the depth each is read at. Depth is one of two values: a tier
`identity`'s visibility reach admits is read in full, and any other tier is read
at whatever its snippets declare about themselves. Depth is
<!-- /planned-change:subject-scope-reach -->
a property of the caller, never of the invocation's location; the location sets
only which home the default read set offers, and a named home is reached from
any location.

- **Also owns:** the artifact-source registry — which exact files, uniform
  directory trees, and immediate package directories of a registered root are
  artifact-source boundaries, of which kind, at which tier, with which reach
  and authorship — and every decision taken from it: reach admission,
  composition of the domain-partitioned global command corpus and the
  mother-only skill catalog, project delivery, and retraction of what a run no
  longer produces. Implementation roots for this ownership are
  `teleclaude/agent_artifacts.py`, `teleclaude/artifact_ownership.py`,
  `teleclaude/global_skills.py`, and distribution code under `teleclaude/install/`.
- **Also does not own:** the publishing declaration that bounds reach (a
  `config` fact), any command's canonical name or emission (facts owned by the
  context that owns that command), or resolution of a name to a document at
  dispatch (an `agent_runtime` decision). This context consumes the first two
  through their published contracts and lays out the corpus the latter resolves.
- **Also publishes:** the registry as a typed contract every source
  consumer reads; its non-overlapping path classification distinguishes the
  authored global-skill catalog master from incorporated package directories.
  It also publishes the composed corpus laid out as `<domain>/<name>` and reach,
  collision, or unclassifiable-source findings that name the offending files.

<!-- planned-change:procedure-activation-gated-on-company -->
- **Also owns:** a procedure's activation declaration — whether agents start it
  by selecting it through an activation trigger, the platform starts it when
  events it subscribes to arrive, or it is supporting knowledge started by
  neither — the validation that a procedure declares at most one mode and
  declares subscriptions only where it is published in the global tier or a
  company's tier, and the
  catalogue consequence: a triggered procedure is offered as self-service work,
  while a subscribed procedure is presented as a configured responsibility and
  is never offered as work an agent may start.
- **Also publishes:** each published procedure's declared event subscriptions
  and the tier it is published at, as part of the publication index. A
  procedure published at global tier subscribes for every company whose
  configured sources emit a matching event; one published in a company's tier
  subscribes for that company only. `integration` consumes this answer and never
  reads procedure metadata itself.
<!-- change:procedure-activation-gated-on-company -->
- **Also owns:** a procedure's activation declaration — whether agents start it
  by selecting it through an activation trigger, the platform starts it when
  events it subscribes to arrive, or it is supporting knowledge started by
  neither — the validation that a procedure declares at most one mode and
  declares subscriptions only where it is published in the global tier, a
  company's tier, or a person's tier, and the
  catalogue consequence: a triggered procedure is offered as self-service work,
  while a subscribed procedure is presented as a configured responsibility and
  is never offered as work an agent may start.
- **Also publishes:** each published procedure's declared event subscriptions
  and the tier it is published at, as part of the publication index. A
  procedure published at global tier subscribes for every activation scope —
  company, person, or project — whose configured sources emit a matching event;
  one published in a company's tier subscribes for that company only, and one
  published in a person's tier for that person only. `integration` consumes this
  answer and never reads procedure metadata itself.
<!-- /planned-change:procedure-activation-gated-on-company -->

### Use cases (index of feature specs)

- **documentation-layout-convergence** — `docs/local/spec/feature/context/documentation-layout-convergence.md` — converging every registered repository on every computer to the documentation layout, one verified commit per repository

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
