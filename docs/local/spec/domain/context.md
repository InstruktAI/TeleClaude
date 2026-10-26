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

- **Also owns:** the structural Blueprint supplied as agent context: extraction,
  graph interpretation, shared-cache generation publication, and freshness-aware
  consumption under `sdlc/spec/codebase-blueprint`. Workflow owns canonical-main
  activation obligations and maintenance outcomes, consumed through its published
  revision and maintenance-observation contracts. Configuration owns the action
  binding declaration; neither coordination nor declaration transfers graph
  policy out of context (`sdlc/policy/domain-ownership`).

- **Also owns:** the resolved read scope — which documentation tiers are
  assembled for a caller, how deeply each is read, and the authorization of the
  selectors that name a tier explicitly. Depth converts `identity`'s visibility
  reach (`local/projects/teleclaude/spec/domain/identity`): a tier it admits is read in
  full. Which tiers a caller may read in full is that reach, decided by
  `identity`; assembly, public-only depth, and the `public` and person-local
  audience facts are documentation rules and resolve here.
- **Also does not own:** the relationships those rules read. Which person a call
  resolves to, which companies that person belongs to, and which projects they
  are assigned to are resolved facts belonging to `identity`; which company owns
  a project is a declaration belonging to `config`. This context consumes both
  through their published contracts and restates neither.

**Resolved read scope** — for one caller, the set of documentation tiers in
reach paired with the depth each is read at. Depth is one of two values: a tier
`identity`'s visibility reach admits is read in full, and any other tier is read
at whatever its snippets declare about themselves. Depth is
a property of the caller, never of the invocation's location; the location sets
only which home the default read set offers, and a named home is reached from
any location.

- **Also owns:** the artifact-source registry — which exact files, uniform
  directory trees, and immediate package directories of a registered root are
  artifact-source boundaries, of which kind, at which tier, with which reach
  and authorship — and every decision taken from it: reach admission,
  composition of the mother-only skill catalog, project delivery, and
  retraction of what a run no longer produces. Implementation roots for this
  ownership are `teleclaude/agent_artifacts.py`,
  `teleclaude/artifact_ownership.py`, `teleclaude/global_skills.py`, and
  distribution code under `teleclaude/install/`.
- **Also does not own:** the publishing declaration that bounds reach (a
  `config` fact), or resolution of a dispatched procedure ID to one published
  procedure at entry (an `agent_runtime` decision). This context consumes the
  first through its published contract and publishes the index the latter
  resolves in.

- **Also publishes:** the registry as a typed contract every source
  consumer reads; its non-overlapping path classification distinguishes the
  authored global-skill catalog master from incorporated package directories.
  It also publishes reach, collision, or unclassifiable-source findings that
  name the offending files.

- **Also owns:** a procedure's activation declaration — whether agents start it
  by selecting it through an activation trigger, the platform starts it when
  events it subscribes to arrive, or it is supporting knowledge started by
  neither — and, for a subscribed procedure, its event type patterns, the one
  home kind it answers — company, person, project, or platform — and which
  agent answers each event: one per home, the default, or one per subject of
  the events. It owns the validation that a procedure declares at most one
  mode, that each subscription is a type pattern `event-catalog`'s matcher
  accepts, that a subscribed procedure declares exactly one home kind and at
  most one agent identity, home or subject, that a home kind or an agent
  identity is declared only beside subscriptions, that it declares
  subscriptions only where it is published in the global tier, a company's
  tier, or a person's tier, and that a company-tier procedure answers company
  events and a person-tier procedure answers person events; and the catalogue
  consequence: a triggered procedure is offered as self-service work, while a
  subscribed procedure is presented as a configured responsibility and is never
  offered as work an agent may start.
- **Also publishes:** each published procedure's declared subscription
  patterns, the home kind it answers, the agent identity it declares, and the
  tier it is published at, as part of the publication index. A procedure
  published at global tier subscribes for every home of its declared kind;
  one published in a company's tier subscribes
  for that company only, and one published in a person's tier for that person
  only. A tier entry whose company or person cannot be read is refused rather
  than published with global reach. `integration` consumes this answer and never
  reads procedure metadata itself.

- **Also owns (attendance):** whether people watch a subscribed procedure's
  agent — attended, the default, or unattended — declared beside its
  subscriptions, validated to be one of the two and declared only beside
  subscriptions, and published with the procedure's other subscription facts
  for `integration` to carry into each activation.

- **Also owns (procedure entry declarations):** the launch declarations a
  procedure carries for the sessions it is the entry of — the session role it
  declares, validated to name a role in `identity`'s agent role catalog and
  required on every procedure a dispatcher, job or subscription names; its
  ordered parameters; and its dispatch defaults — their validation, and their
  publication with the procedure's other published facts. `integration`
  carries them into each activation, and `agent_runtime` and `config` read
  them at a procedure entry; none of them re-derives them. A procedure read
  inside a session, whether or not it declares them, has none of them
  interpreted.
- **Also owns (entry declaration state):** the answer, for one procedure as
  one checkout's publishers resolve it, to which entry declaration that
  checkout holds — the one the procedure's live document carries, the one a
  pending replacement carries together with the delivery that carries it, or
  none — and the report of a documentation source it cannot read as
  unreadable, never as none. What a pending declaration means for an act is
  decided by the context performing that act.

- **Also owns (procedure delivery declarations):** validation and publication
  of the delivery settings declared beside subscriptions and their effective
  defaults. A procedure's required-read graph is its authored dependencies
  alone; delivery settings imply no documentation dependency. The schema owns the field vocabulary; the context
  feature contracts own validation and retrieval
  (`general/spec/snippet-authoring-schema`,
  `local/projects/teleclaude/spec/feature/context/snippet-frontmatter-validation`,
  `local/projects/teleclaude/spec/feature/context/doc-snippet-three-phase-retrieval`).
  Runtime consumes those published facts and owns when and how many events
  reach an agent; context supplies instructions and does not decide event work.

### Use cases (index of feature specs)

- **documentation-layout-convergence** — `docs/local/spec/feature/context/documentation-layout-convergence.md` — converging every registered repository on every computer to the documentation layout, one verified commit per repository

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/agent-artifact-distribution` — how skill packages are validated and published
- `local/projects/teleclaude/design/architecture/context-index` — generating the snippet catalogs
- `local/projects/teleclaude/design/architecture/context-selection` — selecting docs for retrieval
- `local/projects/teleclaude/adr/0016-graphify-as-codebase-blueprint-engine` — Graphify as the codebase blueprint engine
- `local/projects/teleclaude/adr/0023-index-as-single-source-of-truth-for-snippet-metadata` — the index as the source of snippet metadata
- `local/projects/teleclaude/adr/0029-doc-snippet-bodies-state-present-contract` — snippet bodies stating present contract only
- `local/projects/teleclaude/adr/0058-adr-status-supersession` — ADR status supersession
- `local/projects/teleclaude/adr/0059-domain-publication-and-universal-awareness` — domain publication and universal awareness
- `local/projects/teleclaude/adr/0088-deployment-happens-at-the-commit-boundary` — deployment of docs and artifacts at the commit boundary
- `local/projects/teleclaude/adr/0094-publication-activates-from-recorded-commits` — publication only from recorded commits
- `local/projects/teleclaude/adr/0106-a-homes-local-half-is-its-own-identity-namespace` — a home's local half as its own identity namespace
- `local/projects/teleclaude/adr/0107-a-persons-local-half-is-owner-only` — a person's local half readable by its owner only
- `local/projects/teleclaude/adr/0131-the-platforms-documentation-publishes-from-its-project-commits` — platform docs publishing from project commits

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
