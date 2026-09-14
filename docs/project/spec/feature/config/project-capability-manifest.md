---
description: 'Per-project capability manifest in teleclaude.yml: explicit enabled
  toggles for code, docs, and agents; derived checkpoint activation; convergent plumbing.'
visibility: internal
---

# Project Capability Manifest — Spec

## What it is

`teleclaude.yml` declares which platform capabilities a project subscribes to.
Capabilities are explicit in config. The initial declaration is inferred from
repo shape at **onboard** — deterministic structural checks (a Makefile or a
language tree → `code`; snippet frontmatter under `docs/` → `docs`; artifacts
under `agents/` / `.agents/` → `agents`), written into `teleclaude.yml` before
any capability-gated plumbing installs — and later refined by
`telec projects analyze` / `assess`. No **runtime** code path infers a capability
from repo shape; the runtime reads only the written declaration. The checkpoint
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
  (`telec sync`) and artifact transpilation and deployment.

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

- The declaration is the only home of capability state. The installed plumbing —
  the git hooks and the git wrapper — reads the toggles directly from the
  project's `teleclaude.yml`, the same file the runtime resolves, so the shell
  side holds no copy that can go stale or go missing. There is no projection, no
  sentinel, and no marker directory, and therefore no legacy state to
  disambiguate. The plumbing reads only what it decides on: the declaration's
  tier and, for a project declaration, the capability blocks. A capability block
  that is absent, or present without an `enabled` value, resolves to subscribed,
  which is the same default the typed overlay applies, so a project onboarded
  before the manifest keeps today's behavior with no migration. A block whose
  `enabled` value is an unquoted boolean in a spelling the runtime's YAML parser
  accepts is honoured as written, in block form or inline form alike. A block
  whose value the plumbing cannot read as a boolean is refused: the git
  invocation aborts with a message naming `teleclaude.yml` and the block, and no
  capability state is substituted for it — the direction the runtime takes for a
  declaration it cannot read (UC-CFG-CAP-3). The plumbing never falls open and
  never falls closed on such a block, and it claims nothing about the rest of
  the file: overlay validation belongs to the runtime. A global or person
  declaration carries no capability blocks; what the plumbing decides at such a
  repository root is the seal, per `project/design/code-commit`. Because the
  declaration is a file the project tracks, a clone carries the project's real
  capability state before any TeleClaude command has run against it.

- A capability toggle never edits, removes from, or truncates a file the project
  tracks. The only capability plumbing in the project's tracked tree is the
  `.gitattributes` docs-filter line, written once — additively, at onboard, with
  the human in the loop — and never touched again. Enabling or disabling `docs`
  toggles the filter driver in `.git/config` (TeleClaude's own, untracked); with
  the driver absent the `.gitattributes` line is inert, because git treats a
<!-- planned-change:sync-stops-converging-project-setup -->
  filter attribute whose driver is undefined as a no-op. The driver is reconciled
  from the declaration (present iff `docs`) on the same mutating `telec sync` path
  that refreshes the TeleClaude-owned hooks of a `code`-subscribing project;
  `--skip-deploy` leaves both untouched. The safety guarantee — TeleClaude never
  rewrites a project-owned file on a toggle — holds by construction, not by a
  runtime guard.
<!-- change:sync-stops-converging-project-setup -->
  filter attribute whose driver is undefined as a no-op. Converging the installed
  driver and hooks to this declaration is reconciliation's act, contracted in
  `project/spec/feature/reconciliation/project-plumbing-convergence`; this
  declaration is what that act reads. The safety guarantee — TeleClaude never
  rewrites a project-owned file on a toggle — holds by construction, not by a
  runtime guard.
<!-- /planned-change:sync-stops-converging-project-setup -->
<!-- planned-change:sync-stops-converging-project-setup -->
- Onboard is the one-time additive install: it writes the `.gitattributes` line,
  installs the git hooks under the git directory, and configures the filter
  driver. It preserves any hook the project already authored rather than
  overwriting it. After onboard, a toggle takes effect on the plumbing's next
  invocation because the plumbing reads the declaration itself; a mutating
  `telec sync` separately refreshes the TeleClaude-owned hooks and reconciles the
  filter driver. Neither path ever rewrites a project-tracked file.

<!-- change:sync-stops-converging-project-setup -->
- Onboard is the one-time additive install: it writes the `.gitattributes` line,
  then converges the project's plumbing to the declaration it has just written.
  After onboard, a toggle takes effect on the plumbing's next invocation because
  the plumbing reads the declaration itself; what that convergence installs,
  withdraws, or refreshes is contracted in
  `project/spec/feature/reconciliation/project-plumbing-convergence`. Neither path
  ever rewrites a project-tracked file.

<!-- /planned-change:sync-stops-converging-project-setup -->
- A repository carrying no `teleclaude.yml` is not a TeleClaude target: no
  non-adopting path — a sync, the checkpoint engine, the git wrapper — installs
  or reads anything for it, and it is left byte-for-byte untouched. The sole
  exception is explicit adoption: `telec projects onboard` (and `init`) creates
  the `teleclaude.yml` and its inferred declaration — that is the sanctioned act
  that turns a plain repository into a target. Carrying no manifest and carrying
  a broken one are different states: the first is simply not a target, while the
  second is an adopted project whose declaration cannot be read, and that surfaces
  as a failure rather than resolving to any capability state.
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

#### UC-CFG-CAP-3: An unreadable declaration on an adopted project surfaces the failure

```
Given a project carrying a teleclaude.yml that cannot be read
When the capabilities are resolved for that project
Then the read failure surfaces
And no capability state is substituted for the unreadable declaration
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

<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-10: Onboard installs plumbing for a subscribed capability

```
Given a project subscribing docs and code being onboarded
When onboarding installs its capability plumbing
Then the git hooks TeleClaude owns are installed under the git directory
And the docs filter driver is configured
And no capability state is written outside the project's declaration
```

<!-- change:sync-stops-converging-project-setup -->
<!-- /planned-change:sync-stops-converging-project-setup -->
<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-11: Disabling docs never edits the tracked .gitattributes file

```
Given a project whose .gitattributes carries the TeleClaude docs-filter line
When the docs capability is disabled
Then the .gitattributes file is not edited
And the docs filter driver is removed from the git config
And the inert filter line is left in place
```
<!-- change:sync-stops-converging-project-setup -->
<!-- /planned-change:sync-stops-converging-project-setup -->
<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-12: A capability toggle never edits a project-tracked file

```
Given a project with git-tracked files
When any capability toggle is changed
Then no file the project tracks is edited, removed from, or truncated apart from the declaration carrying the toggle
And no capability state is written anywhere outside that declaration
```

<!-- change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-12: A capability toggle never edits a project-tracked file

```
Given a project with git-tracked files
When an agent changes any capability toggle
Then no file the project tracks is edited, removed from, or truncated apart from the declaration carrying the toggle
And no capability state is written anywhere outside that declaration
```

<!-- /planned-change:sync-stops-converging-project-setup -->
<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-13: Onboard does not clobber a hook the project already authored

```
Given a project that already carries its own git hook
When onboarding installs capability plumbing
Then the project's existing hook is preserved rather than overwritten
```

<!-- change:sync-stops-converging-project-setup -->
<!-- /planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-14: A non-adopting path never touches a manifest-less repository

```
Given a repository that carries no teleclaude.yml
And a non-adopting path acts on it — a sync, the checkpoint engine, or the git wrapper
Then no hook, marker, or filter is written or read for it
And the repository is left byte-for-byte unchanged
```

#### UC-CFG-CAP-15: A changed declaration takes effect with no projection pass

```
Given a project whose assessment changes a capability from subscribed to unsubscribed
When that assessment writes the new toggle
Then the installed plumbing resolves the new value on its next invocation
And no separate pass is required to make the change take effect
```

#### UC-CFG-CAP-16: The installed plumbing reads capability state from the declaration

```
Given a project whose code capability is unsubscribed
When the git wrapper runs on a git invocation
Then it decides by reading the capability toggles from the project's teleclaude.yml
And it spawns no interpreter to read them
```

<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-17: An unsubscribed docs capability leaves the snippet pipeline idle

```
Given a project that does not subscribe the docs capability
And that carries snippet sources under docs/
When the sync pipeline runs for that project
Then no snippet is validated, indexed, or published for it
And its subscribed agent artifacts are still deployed
```

<!-- change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-17: An unsubscribed docs capability leaves the snippet pipeline idle

```
Given a project that does not subscribe the docs capability
And that carries snippet sources under docs/
When an agent invokes the sync pipeline for that project
Then no snippet is validated, indexed, or published for it
And its subscribed agent artifacts are still deployed
```

<!-- /planned-change:sync-stops-converging-project-setup -->
<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-18: An unsubscribed agents capability leaves artifact distribution idle

```
Given a project that does not subscribe the agents capability
And that carries agent artifact sources
When the sync pipeline runs for that project
Then no agent artifact is transpiled or deployed for it
And its subscribed snippets are still validated, indexed, and published
```

<!-- change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-18: An unsubscribed agents capability leaves artifact distribution idle

```
Given a project that does not subscribe the agents capability
And that carries agent artifact sources
When an agent invokes the sync pipeline for that project
Then no agent artifact is transpiled or deployed for it
And its subscribed snippets are still validated, indexed, and published
```

<!-- /planned-change:sync-stops-converging-project-setup -->
<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-19: Onboarding a data repository installs no code or docs plumbing

```
Given a repository with no Makefile, no snippet frontmatter under docs/, and no agents artifacts
When the project is onboarded
Then its teleclaude.yml records code, docs, and agents all unsubscribed
And no git hook, docs filter driver, or .gitattributes docs line is installed for it
And the declaration is written before any capability-gated plumbing would run
```

<!-- change:sync-stops-converging-project-setup -->
<!-- /planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-20: A fresh clone honors the declaration before any TeleClaude command runs

```
Given a repository whose tracked teleclaude.yml declares code and docs unsubscribed
And a clone of it on which no telec sync has ever run
When the git wrapper runs on a git invocation inside that clone
Then both capabilities resolve to unsubscribed
And the wrapper execs the real git binary without intercepting the invocation
```

#### UC-CFG-CAP-21: The plumbing reads a hand-authored inline declaration

```
Given a project whose teleclaude.yml disables the code capability in inline-flow form
When the installed plumbing resolves that project's capabilities
Then the code capability resolves to unsubscribed
And it resolves identically to the same declaration written in block form
```

<!-- planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-22: An already-adopted repository picks up the declaration read

```
Given a repository onboarded before the plumbing read the declaration
And whose installed hooks are the ones TeleClaude owns
When a mutating telec sync runs for that repository
Then its TeleClaude-owned hooks are refreshed to read the declaration
And a hook the project authored itself is left in place
```
<!-- change:sync-stops-converging-project-setup -->
<!-- /planned-change:sync-stops-converging-project-setup -->
#### UC-CFG-CAP-24: An unreadable capability block refuses the git invocation

```
Given a project whose teleclaude.yml carries a code capability block whose enabled value is not a boolean
When an agent session invokes git inside that project and the installed plumbing resolves its capabilities
Then the invocation aborts with a message naming teleclaude.yml and the code block
And no capability state is substituted for the unreadable block
And no interpreter is spawned to reach that decision
```

#### UC-CFG-CAP-25: A capability block without an enabled value resolves to subscribed

```
Given a project whose teleclaude.yml carries a code capability block that declares no enabled value
When the capabilities are resolved by the runtime or by the installed plumbing
Then the code capability resolves to subscribed on both readers
```

## Known caveats

- A project manifest key must be declared by the project overlay schema before
  it is written. An undeclared key fails configuration loading and does not
  become load-bearing later.
- Capability toggles gate _mechanisms_, not content: disabling `docs` in a
  repo that still contains snippet frontmatter leaves those files unsynced and
  is surfaced as drift by `telec projects assess`.

- The runtime and the installed plumbing agree on every declaration whose
  capability blocks carry unquoted boolean values. They part on two inputs, in
  opposite directions. A block whose `enabled` value the runtime coerces from a
  quoted string or a number is refused by the plumbing, which reads only
  unquoted booleans. A declaration whose capability blocks are well-formed but
  which fails validation elsewhere in the overlay is refused by the runtime and
  honoured by the plumbing, which reads only the tier and the capability blocks
  and claims nothing about the rest of the file.

## See Also

- docs/project/design/architecture/checkpoint-system.md
- docs/project/procedure/checkpoint-overlay-projection.md
- docs/project/spec/domain/config.md
