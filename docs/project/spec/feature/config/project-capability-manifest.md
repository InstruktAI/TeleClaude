---
description: 'Per-project capability manifest in teleclaude.yml: explicit enabled toggles for code, docs, and agents; derived checkpoint activation; convergent plumbing.'
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

Three toggles, each gating a set of mechanisms:

- `code: { enabled }` — the project holds code under the TeleClaude lifecycle.
  Owns the quality toolchain (`telec code lint` / `test` / `format` /
  `install`), git hooks, worktree rules, and the checkpoint toolchain and
  log-check bindings. The toolchain verbs refuse cleanly ("not a code project")
  when disabled. The sealed-commit surface (`telec code commit` / `add`) and the
  git wrapper's commit interception are not owned by `code` alone — they follow
  `code ∨ docs` (see the derivation rules), because they are the surface that
  records and evidences the commit obligation.
- `docs: { enabled }` — the snippet pipeline: the `docs/** → telec sync` base
  binding, the `.gitattributes` docs filters, and snippet validation, indexing,
  and publication.
- `agents: { enabled }` — agent artifacts: the `agents/**`-family base binding
  (`telec sync` + `telec sessions restart self`) and artifact transpilation and
  deployment.

An unsubscribed capability means the project has no TeleClaude-supported
structure of that kind, so none of the functionality around it activates for that
project — not the checkpoint binding, not the derived plumbing, and not the
pipeline that processes it. Each capability is independent: an unsubscribed one
goes quiet while every subscribed one continues to run.

Task tracking (`telec todo`, `telec bugs`) carries no toggle: a manifest's
existence is the subscription. A data repository holds a `teleclaude.yml` for
exactly this capability, and a code project needs todos for its lifecycle, so
no repo can meaningfully disable it.

Derivation rules:

- The checkpoint engine evaluates a turn iff `code ∨ docs ∨ agents` is enabled
  or the project declares at least one custom binding. Otherwise `agent_stop`
  passes through with no timeline extraction and no evidence scanning.
- The commit obligation is active iff `code ∨ docs` is enabled.
- The sealed-commit surface (`telec code commit` / `add`) and the git wrapper's
  commit interception follow `code ∨ docs` — the same condition as the commit
  obligation — because `telec code commit` is what records and evidences that
  obligation. A project subscribing either `code` or `docs` commits through the
  sealed surface; a project subscribing neither commits with ordinary git and
  the wrapper passes through. The quality toolchain verbs remain gated by `code`
  alone. (The wrapper enforces this inside the tmux agent panes where it runs
  today; extending it to non-tmux agent sessions is separate work and does not
  change this contract.)
- Capability state lives in TeleClaude's own git territory, not the project's
  tracked files. Under the repository's git directory TeleClaude keeps an
  `onboarded` sentinel plus one marker per **enabled** capability; the installed
  plumbing — the git hooks and the git wrapper — reads them by plain existence
  check, never by parsing `teleclaude.yml`. The sentinel is the three-state key:
  **sentinel absent → the repository is legacy/unprojected and the plumbing keeps
  its pre-manifest behavior (all-enabled, today's behavior)**; sentinel present →
  authoritative, so a capability marker present means enabled and absent means
  explicitly unsubscribed. The markers are projected from the declaration by the
  mutating `telec sync` path (and at onboard) as a single idempotent writer, so
  they cannot drift; `--skip-deploy` is read-only and writes no marker state. An
  existing project is initialized — sentinel plus markers — on its first mutating
  sync after upgrade: additive, never a destructive migration. There is no
  recurring reconciler, no drift sweep, and no cross-process coordination.
- A capability toggle never edits, removes from, or truncates a file the project
  tracks. The only capability plumbing in the project's tracked tree is the
  `.gitattributes` docs-filter line, written once — additively, at onboard, with
  the human in the loop — and never touched again. Enabling or disabling `docs`
  toggles the filter driver in `.git/config` (TeleClaude's own, untracked); with
  the driver absent the `.gitattributes` line is inert, because git treats a
  filter attribute whose driver is undefined as a no-op. The driver is reconciled
  from the declaration (present iff `docs`) on the same mutating `telec sync` path
  as the markers; `--skip-deploy` leaves it untouched. The safety guarantee —
  TeleClaude never rewrites a project-owned file on a toggle — holds by
  construction, not by a runtime guard.
- Onboard is the one-time additive install: it writes the `.gitattributes` line,
  installs the git hooks under the git directory, configures the filter driver,
  and writes the markers. It preserves any hook the project already authored
  rather than overwriting it. After onboard, a toggle rewrites only
  TeleClaude-owned git-directory state — a marker, the filter driver — never the
  project's files.
- A repository carrying no `teleclaude.yml` is not a TeleClaude target: nothing
  is installed or read for it, and it is left byte-for-byte untouched. Resolving
  an unreadable declaration to all-subscribed applies only to a project already
  carrying a manifest; it never adopts a repository that carries none.
- The project's `teleclaude.yml`, `.env`, and equivalent native files are
  project-owned and are never removed, superseded, or displaced.
- Each `enabled` defaults to `true` for an already-onboarded project so
  existing repos keep today's behavior; analyze writes explicit values on the
  next assessment.

### Use cases

#### UC-CFG-CAP-1: Omitted capability blocks default to subscribed

```
Given a project overlay that declares no capability blocks
When the project configuration is loaded
Then the code, docs, and agents capabilities each resolve to enabled
And the project's existing maintenance behavior is unchanged
```

#### UC-CFG-CAP-2: An explicitly disabled capability is honored

```
Given a project overlay declaring the code capability disabled
When the project configuration is loaded
Then the code capability resolves to disabled
And the docs and agents capabilities resolve to enabled
```

#### UC-CFG-CAP-3: An unreadable declaration on an adopted project fails open to subscribed

```
Given a project carrying a teleclaude.yml whose contents cannot be parsed
When the capabilities are resolved for that project
Then all three capabilities resolve to enabled
And no capability is silently disabled by the failure
```

#### UC-CFG-CAP-4: A subscribed capability activates the checkpoint engine

```
Given a project subscribing at least one of code, docs, or agents
When an agent turn ends
Then the checkpoint engine evaluates the turn
```

#### UC-CFG-CAP-5: No subscription and no declared binding yields silence

```
Given a project subscribing none of code, docs, or agents
And declaring no checkpoint binding of its own
When an agent turn ends
Then the checkpoint engine evaluates nothing for that turn
And no checkpoint is emitted
And no commit obligation is raised
```

#### UC-CFG-CAP-6: A declared binding alone activates the engine

```
Given a project subscribing none of code, docs, or agents
And declaring at least one checkpoint binding of its own
When an agent turn ends
Then the checkpoint engine evaluates the turn
```

#### UC-CFG-CAP-7: Base bindings attach per subscribed capability

```
Given a project subscribing docs but neither code nor agents
When the effective checkpoint action set is resolved for a changed docs file
Then the docs maintenance action is owed
And no agent-artifact maintenance action is owed
And no toolchain or test maintenance action is owed
```

#### UC-CFG-CAP-8: A project subscribing neither code nor docs raises no commit obligation

```
Given a project subscribing neither code nor docs
When a commit is made in that project
Then it is made through ordinary git rather than the sealed-commit surface
And no commit obligation is recorded for that project
```

#### UC-CFG-CAP-9: The code capability gates the toolchain, not the commit surface

```
Given a project that subscribes docs but not code
When an operator invokes a telec code toolchain subcommand — lint, test, format, or install
Then the command refuses with a message naming the code capability
And telec code commit and telec code add remain available because docs is subscribed
```

#### UC-CFG-CAP-10: Onboard installs plumbing for a subscribed capability

```
Given a project subscribing docs and code being onboarded
When onboarding installs its capability plumbing
Then the git hooks TeleClaude owns are installed under the git directory
And the capability markers TeleClaude owns are written under the git directory
And the docs filter driver is configured
```

#### UC-CFG-CAP-11: Disabling docs never edits the tracked .gitattributes file

```
Given a project whose .gitattributes carries the TeleClaude docs-filter line
When the docs capability is disabled
Then the .gitattributes file is not edited
And the docs filter driver is removed from the git config
And the inert filter line is left in place
```

#### UC-CFG-CAP-12: A capability toggle never edits a project-tracked file

```
Given a project with git-tracked files
When any capability toggle is changed
Then no file the project tracks is edited, removed from, or truncated
And capability state is written only under the git directory TeleClaude owns
```

#### UC-CFG-CAP-13: Onboard does not clobber a hook the project already authored

```
Given a project that already carries its own git hook
When onboarding installs capability plumbing
Then the project's existing hook is preserved rather than overwritten
```

#### UC-CFG-CAP-14: A repository carrying no manifest is never touched

```
Given a repository that carries no teleclaude.yml
When capability plumbing would otherwise be installed or read
Then no hook, marker, or filter is written for it
And the repository is left byte-for-byte unchanged
```

#### UC-CFG-CAP-15: Assessment writes the capability markers when the declaration changes

```
Given a project whose assessment changes a capability from subscribed to unsubscribed
When that assessment writes the new toggle
Then the capability marker under the git directory reflects the new value
And no separate pass is required to make the change take effect
```

#### UC-CFG-CAP-16: The installed plumbing reads capability state by existence check

```
Given a project whose code capability is unsubscribed
When the git wrapper runs on a git invocation
Then it decides by testing for the capability marker
And it does not parse teleclaude.yml
```

#### UC-CFG-CAP-17: An unsubscribed docs capability leaves the snippet pipeline idle

```
Given a project that does not subscribe the docs capability
And that carries snippet sources under docs/
When the sync pipeline runs for that project
Then no snippet is validated, indexed, or published for it
And its subscribed agent artifacts are still deployed
```

#### UC-CFG-CAP-18: An unsubscribed agents capability leaves artifact distribution idle

```
Given a project that does not subscribe the agents capability
And that carries agent artifact sources
When the sync pipeline runs for that project
Then no agent artifact is transpiled or deployed for it
And its subscribed snippets are still validated, indexed, and published
```

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
