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
body and required reads; it never receives either project-wide section.

## Canonical fields

### Use cases

```
Scenario: Mother project sync inflates the global baseline
  Given the current process is running from the Mother project root
  And AGENTS.global.md exists at the Mother project root
  And AGENTS.global.md names the general domain's generated bundle as a Required read
  When the sync step inflates agent baselines
  Then the inflater recursively inlines every @-ref to a depth of at most 20
  And the resulting AGENTS.md is emitted at the Mother project root
  And no CLAUDE.md is emitted alongside it
```

```
Scenario: Non-mother project skips the global source
  Given the current process is running from a non-mother project root
  And AGENTS.global.md does not apply to this project
  When the sync step inflates agent baselines
  Then AGENTS.global.md is not processed
  And only the project's own AGENTS.master.md is inflated
  And only the project's AGENTS.md is emitted under the project root
```

#### UC-AMI3: Progressive baseline expansion respects agent-output scope

```
Scenario: Each agent surface renders its progressive sibling by convention
  Given docs/local/baseline-progressive.md exists alongside docs/local/baseline.md
  And every published domain, general included, carries docs/global/<domain>/baseline-progressive.md alongside docs/global/<domain>/baseline.md
  And no agent Source references either progressive file
  When the inflater renders each domain bundle, the project's AGENTS.md, and the global agent configuration
  Then each progressive sibling is detected by its location and rendered as a baseline index headed by its own scope — "Project" or "Domain"
  And procedures carrying an activation_trigger are auto-included in their scope's "## Activatable Procedures" section with no manifest listing required
  And each activatable entry renders the procedure's description together with its activation trigger
  And the project's own activatable procedures render in a project-scoped "## Activatable Procedures" section
  And every domain's triggered procedures, general's included, surface only in that domain's bundle, never in a project catalog
  And the global agent configuration carries the general baseline index and the general activatable procedures only through the general bundle it inlines, and appends no progressive section of its own
  And the "## Published Domains" awareness section renders in the global agent configuration only, never in a project's AGENTS.md
  And every listed published domain's required activation trigger from its owner's project configuration renders enriched on its Published Domains line
  And a publishes entry whose trigger is missing, blank, multiline, or over-length fails config load and blocks the sync
  And @-ref expansion inlines every referenced snippet verbatim with no filename-based diversion
  And procedure bodies are NOT inlined into the project's AGENTS.md
```

#### UC-AMI4: A hand-listed triggered procedure blocks the sync

```
Scenario: Hand-listed triggered procedure blocks the sync
  Given a baseline-progressive.md manifest listing a procedure snippet that carries an activation_trigger
  When the sync step inflates that scope's agent baseline
  Then the build fails with a validation error naming the manifest and the offending ref
  And the error directs removing the ref from the manifest
  And the failure is not downgradable to a warning
```

#### UC-AMI5: Pending snippets stay invisible to every transpiled surface

```
Scenario: A snippet carrying delivered_by is excluded from agent-facing output
  Given a snippet whose frontmatter and index entry carry a non-empty delivered_by
  And that snippet is a triggered procedure curated by a baseline-progressive.md manifest and referenced by an @-ref
  When the inflater renders the baseline index, the activatable catalog, the Published Domains counts, and the inlined bodies
  Then the snippet contributes no baseline index entry
  And the snippet contributes no activatable procedures entry
  And the snippet is excluded from its domain's Published Domains snippet count
  And the snippet's body is not inlined into any generated entrypoint
  And the sync does not block on the manifest curating it
```

#### UC-AMI6: Generated entrypoints carry no authoring sentinels

```
Scenario: Master-file lock sentinels are stripped from generated output
  Given a master file whose body opens and closes with a LOCKED_FILE HTML-comment sentinel
  When the inflater generates the deployed entrypoint from it
  Then the generated file contains neither sentinel
  And the master file retains both sentinels unchanged
```

#### UC-AMI7: Project-wide progressive material is root-only

```
Scenario: Root and nested masters inflate at different scopes
  Given a project contains AGENTS.master.md at the repository root
  And one or more nested directories contain their own AGENTS.master.md
  When sync inflates every master
  Then the repository-root AGENTS.md contains the project baseline index and project activatable-procedure catalog
  And every nested AGENTS.md contains only its nested master's expanded authored content and required reads
  And no nested AGENTS.md contains project-wide progressive baseline material
```

```
Scenario: Recursive ref expansion fails at the depth limit
  Given an @-ref tree whose expansion depth would exceed 20 levels
  When the inflater walks the tree
  Then expansion stops at depth 20
  And the build fails with a depth-limit error
  And no truncated AGENTS.md is emitted
```

```
Scenario: Idempotent re-inflation produces byte-identical output
  Given AGENTS.master.md and all referenced snippets are unchanged since the last sync
  When inflation runs again
  Then YAML frontmatter is dumped with stable key ordering
  And the Deployed AGENTS.md is byte-identical to the previous run
  And no spurious diff appears in the working tree
```

#### UC-AMI8: A subscription-activated procedure is a configured responsibility, not self-service work

```
Scenario: The catalogue offers only what an agent may start itself
  Given a procedure declares the events that activate it
  When the inflater renders that scope's agent baseline
  Then the procedure contributes no entry to the section an agent selects discretionary work from
  And the baseline still presents the procedure as a responsibility that is already owned
  And that presentation names the events the procedure answers to
```

#### UC-AMI9: The Published Domains roster follows the publishers' declarations

```
Scenario: The roster lists every declared domain the global configuration does not already carry
  Given registered publishers declare their domains with triggers in business.publishes
  And the global agent configuration names one of those domains' generated bundle as a Required read
  And the deployed index also carries person and company tier entries and domain procedures declaring their own activation_trigger
  When the inflater renders the "## Published Domains" section
  Then the section lists each declared domain once, with the trigger its publisher recorded with that domain's published documents
  And the mother's publication stops before replacing the deployed generation when a published domain carries no recorded trigger, naming that domain
  And a domain whose bundle the global agent configuration inlines is not listed
  And no snippet's activation_trigger is rendered as a domain's trigger
  And person and company tier entries contribute no line and fail nothing
```

#### UC-AMI10: Every home master compiles into its home's entrypoint

```
Scenario: Home publication inflates the fixed home master set
  Given the platform home's recorded source holds its root AGENTS.master.md
  And a declared person home and a declared company home each hold a root AGENTS.master.md, and the company home a help-desk/AGENTS.master.md
  When committed-state publication activates that recorded source
  Then an AGENTS.md is written beside each of those masters
  And each AGENTS.md carries its master's expanded authored content and required reads, with no @ import left in it
  And every documentation read it inlines comes from the deployed documentation, except the home's own recorded tier source
  And no AGENTS.md written there carries a project baseline index or activatable-procedure catalog
  And no CLAUDE.md is written beside any of them
  And the home's working tree holds no change the home's history would record
```

```
Scenario: A master outside the fixed home master set is not compiled
  Given a home holds an AGENTS.master.md at a path other than the home root, a declared person's or company's root, or a declared company's help desk
  And that path may lie under a home's docs
  When committed-state publication activates the platform home's recorded source
  Then no AGENTS.md is written beside that master
  And no generated entrypoint lands in a retained subtree
```

#### UC-AMI11: The Mother's global publication refreshes home entrypoints

```
Scenario: A republished bundle reaches every home entrypoint that inlines it
  Given a home master requires a domain bundle the Mother publishes
  When the Mother's global publication replaces that bundle
  Then the home's AGENTS.md is recompiled from its unchanged master
  And it carries the replaced bundle's content
  And no commit in the platform home is needed for it
```

```
Scenario: A home master that no longer inflates fails the refresh visibly
  Given the Mother's publication replaced a bundle
  And one home master no longer inflates against it
  When the refresh runs
  Then every other home entrypoint is recompiled
  And the failing master's previous entrypoint is left in place
  And the Mother's publication reports failed, naming home refresh as the reason, after its own deployment completed
  And recovery replays that publication, which retries the refresh
```

```
Scenario: A home generation its own publication never compiled is not refreshed
  Given the platform home's published generation was published without compiling its home entrypoints
  When the Mother's global publication completes
  Then no home entrypoint is written or removed
  And the Mother's publication does not fail on the home's account
```

#### UC-AMI12: A leftover generated pointer is removed; an authored CLAUDE.md is kept

```
Scenario: Only the retired generated pointer is retracted
  Given a directory holds an AGENTS.master.md
  And beside it a CLAUDE.md, tracked neither at the recorded commit nor in the repository's current HEAD and absent from its index, whose entire content is the pointer import of AGENTS.md
  And another directory with a master holds a CLAUDE.md with any other content, or one its repository tracks
  And a third holds a pointer CLAUDE.md the recorded commit lacks but the repository's current HEAD tracks or its index stages
  And another holds a pointer the repository's current HEAD tracks although it is removed from the index
  When sync inflates those masters
  Then the untracked pointer CLAUDE.md is deleted
  And the other CLAUDE.md is left byte-identical
  And the HEAD-tracked or index-staged pointer is left byte-identical
  And the pointer HEAD tracks but the index no longer holds is left byte-identical
  And each directory's AGENTS.md is written
```

#### UC-AMI13: Claude Code reads the entrypoint beneath an ancestor CLAUDE.md

```
Scenario: The deployed Claude user settings make AGENTS.md load beside CLAUDE.md
  Given TeleClaude has deployed its Claude user settings on the machine
  And a directory above a project root holds a CLAUDE.md the human authored
  When a Claude Code session starts in that project root
  Then the project's generated AGENTS.md is among the loaded instruction files
  And the ancestor CLAUDE.md still loads
  And an AGENTS.md that some CLAUDE.md already imports is loaded once
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
  dead weight — auto-inclusion already surfaces it — and sync flags it for
  removal from the manifest.
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
