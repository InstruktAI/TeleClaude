---
description: 'AGENTS.global.md (mother-project) and per-project AGENTS.master.md are inflated into deployed AGENTS files by recursively expanding @-refs.'
visibility: 'public'
---

# AGENTS.master Inflation — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Inflation is the build-time step that turns hand-authored agent baseline
Sources — the platform-wide `AGENTS.global.md` (owned by the Mother project)
and each project's `AGENTS.master.md` — into self-contained Deployed `AGENTS.md`
files for every project. Inflation works by recursively expanding `@path.md`
inline references inside the source, so the Deployed artifact is one
self-contained document an agent CLI can read without resolving a tree of
refs at runtime.

Inflation runs as a Sync step. The Source authors hold the canonical content;
inflation produces the Deployed `AGENTS.md` beside each master, and that
`AGENTS.md` is the only file it writes there — no per-agent companion such as
a `CLAUDE.md` pointer. A project's masters inflate during that project's sync.
The home masters are a fixed set: the platform home's root `AGENTS.master.md`,
each declared person's and company's root master, and each declared company's
`help-desk/AGENTS.master.md`. They inflate when the platform home's recorded
source is published, and again whenever the Mother's global publication
replaces documentation they inline; a refresh that cannot recompile one
reports the Mother's publication as failed, so a lagging home entrypoint is
always a visible, replayable failure. That refresh recompiles only a home
generation whose entrypoints the home's own publication compiled; an earlier
generation is left to the home's next publication. A master anywhere else in a home,
including under a home's docs, is not compiled, so no generated entrypoint
ever lands in a retained subtree. A home entrypoint inlines only activated,
deployed documentation — never a publisher's unpublished source — apart from
the home's own recorded tier source. Every Deployed `AGENTS.md` is fully
inlined: it carries no `@` import for an agent CLI to resolve.

Only the repository-root `AGENTS.master.md` is a project entrypoint. Its
generated `AGENTS.md` receives the project-wide progressive baseline index and
activatable-procedure catalog. A nested master produces only its own expanded
body and required reads; it never receives either project-wide section. Generated
entrypoints omit the `LOCKED_FILE` sentinel comments found in source masters. The
global agent configuration's Published Domains roster lists publisher-declared
domains not already inlined by that configuration, with each publisher's
declared trigger. Each Activatable Procedures entry shows its description and
activation trigger; each Configured Responsibilities entry shows its description
and subscribed events.

## Canonical fields

### Use cases

#### UC-AMI3: Progressive baseline expansion respects agent-output scope

#### UC-AMI4: A hand-listed triggered procedure blocks the sync

#### UC-AMI5: Pending snippets stay invisible to every transpiled surface

#### UC-AMI6: Generated entrypoints carry no authoring sentinels

#### UC-AMI7: Project-wide progressive material is root-only

#### UC-AMI8: A subscription-activated procedure is a configured responsibility, not self-service work

#### UC-AMI9: The Published Domains roster follows the publishers' declarations

#### UC-AMI10: Every home master compiles into its home's entrypoint

#### UC-AMI11: The Mother's global publication refreshes home entrypoints

#### UC-AMI12: A leftover generated pointer is removed; an authored CLAUDE.md is kept

#### UC-AMI13: Claude Code reads the entrypoint beneath an ancestor CLAUDE.md

```gherkin
Scenario: Start Claude Code with project and ancestor instructions
  Given an operator has a project beneath a directory with a human-authored CLAUDE.md
  When they start a Claude Code session in that project
  Then both the project and ancestor instructions apply
  And an AGENTS.md already imported by a CLAUDE.md is applied only once
```

### Cross-context references

- **config** — Provides the project root list and the Mother project identity
  consulted at gating time.
- **agent_runtime** — Consumes the Deployed `AGENTS.md` at agent CLI startup.
  The inflated file is the runtime baseline. Claude Code reads it through the
  project-instructions setting TeleClaude's deployed Claude user settings
  carry (`third-party/claude-code/instruction-files`).
- **reconciliation** — The home's retained set admits the home, platform help
  desk, person, company, and company help desk masters and never a generated
  `AGENTS.md`; a master commit in the
  platform home owes the publication that inflates it.

## Known caveats

- `baseline-progressive.md` is a **location convention**, never a reference
  target: it exists as a sibling of its `baseline.md` and is detected and
  appended by the inflater for each surface — domain bundle and project
  `AGENTS.md` — through one shared collection and rendering path; only the
  scope of the activatable set differs per surface. The global agent
  configuration has no progressive sibling of its own: it receives the general
  domain's through the general bundle it names as a Required read.
  No Source references it, and `@`-ref expansion inlines every referenced
  snippet verbatim for every target agent (Claude, Codex, Gemini) with no
  filename-based diversion.
- Manifests curate; frontmatter declares. The scope-headed baseline index
  renders the manifest's curated entries; the "Activatable Procedures" section
  is auto-collected from `activation_trigger` declarations in the scope's index.
  A triggered procedure hand-listed in a `baseline-progressive.md` manifest is
  dead weight — auto-inclusion already surfaces it — and sync blocks, even in
  warn-only mode, with a finding naming the manifest and reference to remove.
- `delivered_by` is the pending gate for the whole transpiler, applied once per
  surface: baseline index entries, activatable procedures, Published Domains
  counts, and inlined bodies all skip a snippet that declares it. The merged
  deployed `index.yaml` still carries pending entries — `telec docs index
--target <slug>` is built on them — so the exclusion is a rendering rule, not
  an indexing one. Delivery clears the field and the snippet appears with no
  second edit; a manifest may therefore curate a snippet before it exists
  without blocking the sync.
- Published Domains is a global-only section. A project's `AGENTS.md` is
  scoped to that project, and the platform-wide domain roster belongs to the
  global agent configuration; rendering it per project duplicated the same
  roster into every entrypoint. Publisher trigger validation is independent of
  it — resolving the declarations is a sync precondition, so an unusable
  trigger still blocks a project-only sync that renders no awareness section.
- Authoring sentinels are stripped from generated output. The `LOCKED_FILE`
  comment addresses whoever opens a master file to edit it; a generated
  entrypoint is never edited, so carrying the sentinel through would spend an
  agent's context on an instruction it cannot act on.
- Activation is a coverage-gap device on an enforcement gradient at the
  procedure level: triggered procedures surface once, in their domain's
  bundle, and the general bundle's are always on because the global agent
  configuration inlines it. At the domain level there is no gap to judge:
  every published domain carries a required activation trigger in its
  owner's project configuration, rendered enriched on its Published Domains
  line — with domain procedures out of the always-on catalog, that line is a
  domain's only always-on tripwire, so a publishes entry without a trigger
  fails config load rather than delivering an undiscoverable domain. A domain
  whose bundle the global agent configuration already inlines needs no
  tripwire and gets no line; its trigger is still required, because the
  declaration is validated the same way for every domain.
- The global agent configuration inlines the general bundle generated earlier
  in the same deploy: documentation composition precedes transpilation, so the
  global baseline tracks the general sources of the run that publishes it, and
  a run that composes no documentation inlines the previously published bundle.
- A domain's trigger enters the deployed generation with its publisher's own
  publication of that domain's documents, so trigger and documents always come
  from the same revision. The mother's publication requires a recorded trigger
  for every published domain; when one is missing it stops before the deployed
  generation is replaced, and it succeeds on replay once that domain's publisher
  has published.

- The depth limit of 20 is a static constant in the inflater. A legitimately
  deeper ref tree would fail without a configuration knob — the fix is to
  flatten the ref tree at the Source, not to raise the limit.
- Mother-project gating is filesystem-path equality against the configured
  Mother root. There is no per-project ACL beyond "is this the Mother repo";
  any project whose root matches the configured path receives the global
  treatment.
- Source naming is asymmetric: the platform-wide Source is `AGENTS.global.md`,
  while the per-project Source is `AGENTS.master.md`. The asymmetry is
  intentional (different roles, different scopes) but easy to confuse with
  the Deployed `AGENTS.md` output.
- Nested `AGENTS.master.md` files are directory-local wrappers, not additional
  project entrypoints. Their inflation shares recursive ref expansion with the
  root master but deliberately does not share its progressive project sections.
- Embedded executable directives are resolved inline during expansion; this
  means the Deployed file can capture the output of a directive at sync time
  rather than at agent runtime.
