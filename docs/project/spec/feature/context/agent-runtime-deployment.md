---
description: 'Two-phase deployment of transpiled artifacts to per-agent home dirs, with Codex commands routed to a shared TeleClaude dir and global docs composed as a per-domain symlink with exactly one owning publisher per domain.'
visibility: 'public'
---

# Agent Runtime Deployment — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

The phase of Sync that writes Deployed outputs each agent CLI reads at
runtime. When invoked via `telec sync`, the distribution step always runs
in deploy mode (there is no no-deploy mode through the CLI). The deploy
path runs two phases:

1. **Global phase** — sources from `agents/` (Mother project only) are
   built under a transient distribution directory and then deployed
   to per-agent user-home roots: `~/.claude/`, `~/.gemini/`, `~/.codex/`.
   The publishing gate ensures the global agent-artifact source list is
   only populated on the Mother project. Global documentation, in contrast,
   is contributed by every project for the domains it publishes (see below).
2. **Local phase** — sources from `.agents/` (any project) are built
   under a transient distribution directory and then deployed to the
   project root. Codex commands are an exception: they route to
   `~/.teleclaude/commands/` (NOT `~/.codex/commands/`) so commands are
   reusable across projects.

After both phases, the global documentation tree is exposed at
`~/.teleclaude/docs/` as a **per-domain composition with exactly one owning
publisher per domain**. The root is a real directory rebuilt each sync. Each
published domain is a single symlink `~/.teleclaude/docs/<domain>` → the owning
publisher's `docs/global/<domain>/` directory; the cross-cutting `general/` is a
single symlink to the Mother repo's `docs/global/general`. A symlink has exactly
one target, so one-owner-per-domain is structural — two publishers cannot merge
into one domain. A domain's snippet files resolve through the directory symlink
as live views of the owner's source (no copy). The valid domains are exactly the
union of every registered project's `business.publishes`; TeleClaude holds no
central allow-list of valid domains, and adding a domain needs only a project
that declares and serves it.

The registered-publisher set is maintained automatically: a deploy-mode
`telec sync` from a project declaring `business.publishes` registers that
project's durable root, so declaring and serving a domain is sufficient for
platform-wide recognition with no separate registration step. Split detection
(below) evaluates every registered publisher, so a self-registered publisher
participates in the one-owner-per-domain hard block like any other.

Sync-time split detection runs before composition: if more than one registered
project declares the same domain in `business.publishes`, the deploy
HARD-BLOCKS (exits non-zero, composes nothing) with `split domain ownership:
<domain> claimed by <A> and <B>`. The single declaring project is the owner
whose folder the domain symlinks to. This is the one cross-publisher integrity
rule: a domain has exactly one owning publisher.

The deploy writes the merged `index.yaml` at the root — the union of every
owner's per-domain global index. Because no two owners share a domain, the union
carries no cross-owner id collision to resolve. The single filesystem root
`~/.teleclaude/docs` is preserved so the three readers that resolve global docs —
the SessionStart hook, `telec docs`, and the index build — read one root
unchanged.

For each published domain the deploy inflates the owner's `baseline.md` (and
`baseline-progressive.md`) and writes the result as `domain-baseline-bundle.md`
**inside the owner's `docs/global/<domain>/` directory** (gitignored in the
source tree). Because `~/.teleclaude/docs/<domain>` is a symlink to that
directory, `~/.teleclaude/docs/<domain>/domain-baseline-bundle.md` resolves
through it — the SessionStart hook path is unchanged. With one owner per domain
the bundle is single-source: there is no cross-publisher dedup. The SessionStart
hook reads that bundle to inject the domain's process-enforcement baseline.
Global third-party docs are read from the mother repo source (`docs/third-party/`),
not from under the docs tree.

When the distribution step is invoked directly in no-deploy mode, agent
artifacts are emitted to `project_root/dist/global` and
`project_root/dist/local` (not transient dirs), no copies are made to
`~/.<agent>/`, and documentation deployment is skipped. This direct
no-deploy mode is for developers/CI inspecting build output, not for
`telec sync`.

## Canonical fields

### Use cases

```
Scenario: UC-ARD1 Mother project full sync with deploy
  Given the project is the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then global sources from agents/ deploy to ~/.claude/, ~/.gemini/, and ~/.codex/
  And local sources from .agents/ deploy to the project root
  And Codex commands deploy to ~/.teleclaude/commands/
  And AGENTS.override.md is written to the project root for Codex override detection
  And docs/global/ is composed per domain into the ~/.teleclaude/docs/ root
```

```
Scenario: UC-ARD2 Non-mother project sync skips global agent-artifact phase
  Given the project is not the Mother project
  And sync is invoked in deploy mode
  When the distribution pipeline runs
  Then the global phase produces no agent-home artifact writes
  And the local phase deploys .agents/ to the project root
  And Codex commands still route to ~/.teleclaude/commands/
  And each domain the project owns in business.publishes is a single symlink ~/.teleclaude/docs/<domain> to the project's docs/global/<domain>
```

```
Scenario: UC-ARD3 Sync from a worktree uses worktree docs
  Given sync runs from a git worktree of the Mother project
  When the canonical-root resolver identifies the canonical root
  Then the docs source is the current worktree checkout
  And a Mother-repo-owned domain's symlink resolves to the worktree's branch, not main
```

```
Scenario: UC-ARD4 Sync composes the per-domain single-owner docs tree
  Given two publishers, each declaring in business.publishes a different domain it owns
  When the documentation deployment step runs
  Then any stale real or symlinked ~/.teleclaude/docs from an older deploy is replaced
  And ~/.teleclaude/docs is a real directory
  And each published domain is a single symlink ~/.teleclaude/docs/<domain> to its owning publisher's docs/global/<domain> directory
  And ~/.teleclaude/docs/general resolves to the Mother repo's docs/global/general
  And ~/.teleclaude/docs/index.yaml is the union of every owner's global index
  And each published domain's domain-baseline-bundle.md resolves through the domain symlink to the owner's source directory
  And a snippet removed from a source domain disappears from ~/.teleclaude/docs/<domain> on the next deploy with no orphan link
```

```
Scenario: UC-ARD5 Distribution invoked directly in no-deploy mode
  Given the distribution step is invoked directly (not through telec sync) in no-deploy mode
  When the distribution pipeline runs
  Then agent artifacts are emitted under project_root/dist/global and project_root/dist/local
  And no transient distribution dirs are used
  And no writes occur to ~/.claude/, ~/.gemini/, ~/.codex/
  And documentation deployment is NOT performed
  And the dist/ output is left in place for inspection
```

```
Scenario: UC-ARD6 SessionStart injects the generated domain bundle
  Given a session whose command resolves to a domain with a generated bundle
  When the SessionStart hook builds additional context
  Then it reads ~/.teleclaude/docs/<domain>/domain-baseline-bundle.md
  And injects the inflated domain process-enforcement baseline before the first user message
```

```
Scenario: UC-ARD7 SessionStart surfaces a missing domain bundle
  Given a session whose command resolves to a domain whose generated bundle is absent
  When the SessionStart hook builds additional context
  Then it surfaces a visible warning naming the missing ~/.teleclaude/docs/<domain>/domain-baseline-bundle.md
  And the mandatory baseline is never silently dropped
```

```
Scenario: UC-ARD8 Split domain ownership blocks the deploy
  Given two registered publishers that both declare the same domain in business.publishes
  When the documentation deployment step runs
  Then the deploy aborts with a sync-blocking error naming the split domain and both publishers
  And nothing is composed and no merged index is written
```

<!-- planned:fix-telec-sync-domain-inconsistencies -->

```
Scenario: UC-ARD9 Domain bundle surfaces its baseline-progressive activatable procedures
  Given a published domain whose baseline-progressive.md lists a procedure snippet carrying an activation_trigger
  When the deploy inflates that domain's domain-baseline-bundle.md
  Then the bundle carries an "## Activatable Procedures" section listing that procedure with its activation trigger
  And the procedure is not dropped from the bundle
```

<!-- /planned:fix-telec-sync-domain-inconsistencies -->

### Cross-context references

- **agent_runtime** — each agent CLI reads its `~/.<agent>/` tree at
  runtime. The deployed directories are the publish/consume boundary
  between Context (publisher) and agent_runtime (consumer).
- **config** — supplies the project root, the Mother project resolution used
  by the agent-artifact publishing gate, and each project's `business.publishes`
  declarations used to compose the docs tree and derive the valid-domain set.

## Known caveats

- Codex commands routing to `~/.teleclaude/commands/` (rather than
  `~/.codex/commands/`) is deliberate cross-project sharing. It
  surprises operators who expect symmetry with `~/.claude/` and
  `~/.gemini/`. The decision is intentional, not a bug.
- Documentation links are read-only by convention. Each per-domain directory
  symlink resolves onto its owning publisher's live source directory, so a stray
  edit through it mutates source; agents treat deployed docs as read-only.
- Worktree-aware docs sourcing prevents the easy bug of "synced from a
  worktree but deployed main-branch docs". A worktree whose `docs/` is
  missing, however, falls back silently rather than erroring.
- The distribution step is always fatal: a non-zero distribution exit propagates
  and fails the sync (there is no suppress-on-warn mode). A split domain
  ownership declaration and a bundle-inflation failure both abort the deploy this
  way. The docs watcher, which must not block, catches that failure at its own
  subprocess boundary instead.
- The deployed `index.yaml` is the union of every owner's source per-domain
  `index.yaml`; each source index already carries `~/.teleclaude` paths, so the
  merge is a union of entries with no path rewrite. With one owner per domain the
  union has no cross-owner id collision to resolve. Consumers see identical paths
  from any owner's working tree and the deployed view — there is no deploy-time
  index divergence.
