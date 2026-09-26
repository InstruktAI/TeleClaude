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
language tree → `code`; snippet frontmatter under `docs/` → `docs`; authored
artifacts under `agents/` → `agents`, never `.agents/`, which is a delivery
location), written into `teleclaude.yml` before any capability-gated plumbing
installs — and later refined by the project-analysis and quality-configuration assessment procedures. No **runtime** code path infers a capability
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
- `docs: { enabled }` — the snippet pipeline: the `docs/**` publication base
  binding, the `.gitattributes` docs filters, and snippet validation, indexing,
  and publication.
- `agents: { enabled }` — agent artifacts: the `agents/**`-family base binding
  and artifact transpilation and deployment.

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

<!-- planned-change:config-migration-chain -->
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
<!-- change:config-migration-chain -->
- The declaration is the only home of capability state. The installed plumbing —
  the git hooks and the git wrapper — resolves the toggles through the runtime's
  own reading of the repository root's own declaration: brought to its current
  shape by the configuration migration list
  (`project/spec/feature/config/document-migration`); and its tier and each
  capability block read the way the runtime's loader reads them — environment
  references resolved from the declaration's sibling `.env` — and validated with
  the runtime's own models. The two readers therefore
  answer alike for every tier and every capability block of the same
  declaration, and a declaration that loads in the runtime never blocks git. The plumbing reads only what it decides
  on: the declaration's tier and, for a project declaration, the capability
  blocks. A block the runtime cannot read as a capability block is refused: the
  git invocation aborts with a message naming `teleclaude.yml` and the block, and
  no capability state is substituted for it — the direction the runtime takes for
  a declaration it cannot read (UC-CFG-CAP-3). The plumbing never falls open and
  never falls closed on such a block, and it claims nothing about the rest of the
  file: overlay validation belongs to the runtime. The plumbing keeps the answer
  for a declaration it has resolved, together with every file that answer was
  read from, and serves repeated reads from it without starting an interpreter.
  The kept answer is a cache of the runtime's answer, never a source: a change to
  any of those files, or an advance of the installation's code, discards it, so
  it never answers for an input state or an installation it was not resolved
  from. A global or person declaration carries no capability
  blocks; what the plumbing decides at such a repository root is the seal, per
  `project/design/code-commit`. Because the declaration is a file the project
  tracks, a clone carries the project's real capability state before any
  TeleClaude command has run against it.
<!-- /planned-change:config-migration-chain -->

- A capability toggle never edits, removes from, or truncates a file the project
  tracks. The only capability plumbing in the project's tracked tree is the
  `.gitattributes` docs-filter line, written once — additively, at onboard, with
  the human in the loop — and never touched again. Enabling or disabling `docs`
  toggles the filter driver in `.git/config` (TeleClaude's own, untracked); with
  the driver absent the `.gitattributes` line is inert, because git treats a
  filter attribute whose driver is undefined as a no-op. Converging the installed
  driver and hooks to this declaration is reconciliation's act, contracted in
  `project/spec/feature/reconciliation/project-plumbing-convergence`; this
  declaration is what that act reads. The safety guarantee — TeleClaude never
  rewrites a project-owned file on a toggle — holds by construction, not by a
  runtime guard.
- Onboard is the one-time additive install: it writes the `.gitattributes` line,
  then converges the project's plumbing to the declaration it has just written.
  After onboard, a toggle takes effect on the plumbing's next invocation because
  the plumbing reads the declaration itself; what that convergence installs,
  withdraws, or refreshes is contracted in
  `project/spec/feature/reconciliation/project-plumbing-convergence`. Neither path
  ever rewrites a project-tracked file.

- A repository carrying no `teleclaude.yml` is not a TeleClaude target: no
  non-adopting path — a sync, the checkpoint engine, the git wrapper — installs
  or reads anything for it, and it is left byte-for-byte untouched. The sole
  exception is explicit adoption: `telec config project init` creates
  the `teleclaude.yml` and its inferred declaration — that is the sanctioned act
  that turns a plain repository into a target. Carrying no manifest and carrying
  a broken one are different states: the first is simply not a target, while the
  second is an adopted project whose declaration cannot be read, and that surfaces
  as a failure rather than resolving to any capability state.
- The project's `teleclaude.yml`, `.env`, and equivalent native files are
  project-owned and are never removed, superseded, or displaced.
<!-- planned-change:config-migration-chain -->
- Each `enabled` defaults to `true` for an already-onboarded project so
  existing repos keep today's behavior; analyze writes explicit values on the
  next assessment.
<!-- change:config-migration-chain -->
- A capability block that is absent, or present without an `enabled` value,
  resolves to unsubscribed: only an explicit value claims a capability.
  Registration declares every capability the document leaves undeclared, with
  the value inferred from repo shape, and assessment refines the declarations. A
  registered project whose declaration was written while an omitted block still
  meant subscribed keeps those subscriptions: the configuration migration list
  brings its declaration forward with each of them written explicitly, and the
  same holds for its linked worktrees' copies. A declaration the registries do
  not name gains no subscription from that migration.
<!-- /planned-change:config-migration-chain -->

### Use cases

<!-- planned-change:config-migration-chain -->
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
<!-- change:config-migration-chain -->
#### UC-CFG-CAP-1: Omitted capability blocks resolve to unsubscribed

```
Given a project overlay at the current configuration version that declares no capability blocks
When the project configuration is loaded
Then the code, docs, and agents capabilities each resolve to disabled
And no capability-gated mechanism activates for the project
```

#### UC-CFG-CAP-2: An explicitly disabled capability is honored

```
Given a project overlay declaring the code capability disabled and the docs and agents capabilities enabled
When the project configuration is loaded
Then the code capability resolves to disabled
And the docs and agents capabilities resolve to enabled
```
<!-- /planned-change:config-migration-chain -->


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

#### UC-CFG-CAP-10:

#### UC-CFG-CAP-11:

#### UC-CFG-CAP-12: A capability toggle never edits a project-tracked file

```
Given a project with git-tracked files
When an agent changes any capability toggle
Then no file the project tracks is edited, removed from, or truncated apart from the declaration carrying the toggle
And no capability state is written anywhere outside that declaration
```

#### UC-CFG-CAP-13:

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

<!-- planned-change:config-migration-chain -->
#### UC-CFG-CAP-16: The installed plumbing reads capability state from the declaration

```
Given a project whose code capability is unsubscribed
When the git wrapper runs on a git invocation
Then it decides by reading the capability toggles from the project's teleclaude.yml
And it spawns no interpreter to read them
```
<!-- change:config-migration-chain -->
#### UC-CFG-CAP-16: The installed plumbing answers a repeated read without an interpreter

```
Given the installed plumbing has kept its answer for a project's declaration
And since then no file that answer was read from has changed and the installation's code has not advanced
When the git wrapper runs on a git invocation
Then it decides from the capability subscriptions the runtime resolves for that declaration
And it spawns no interpreter to read them
```
<!-- /planned-change:config-migration-chain -->


#### UC-CFG-CAP-17: An unsubscribed docs capability leaves the snippet pipeline idle

```
Given a project that does not subscribe the docs capability
And that carries snippet sources under docs/
When an agent invokes the sync pipeline for that project
Then no snippet is validated, indexed, or published for it
And its subscribed agent artifacts are still deployed
```

#### UC-CFG-CAP-18: An unsubscribed agents capability leaves artifact distribution idle

```
Given a project that does not subscribe the agents capability
And that carries agent artifact sources
When an agent invokes the sync pipeline for that project
Then no agent artifact is transpiled or deployed for it
And its subscribed snippets are still validated, indexed, and published
```

#### UC-CFG-CAP-19:

#### UC-CFG-CAP-20: A fresh clone honors the declaration before any TeleClaude command runs

```
Given a repository whose tracked teleclaude.yml declares code and docs unsubscribed
And a clone of it on which no publication has ever run
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

#### UC-CFG-CAP-22:

<!-- planned-change:config-migration-chain -->
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
<!-- change:config-migration-chain -->
#### UC-CFG-CAP-24: An unreadable capability block refuses the git invocation

```
Given a project whose teleclaude.yml carries a code capability block whose enabled value the runtime cannot read as a boolean
When an agent session invokes git inside that project and the installed plumbing resolves its capabilities
Then the invocation aborts with a message naming teleclaude.yml and the code block
And no capability state is substituted for the unreadable block
```

#### UC-CFG-CAP-25: A capability block without an enabled value resolves to unsubscribed

```
Given a project whose teleclaude.yml, at the current configuration version, carries a code capability block that declares no enabled value
When the capabilities are resolved by the runtime or by the installed plumbing
Then the code capability resolves to unsubscribed on both readers
```
<!-- /planned-change:config-migration-chain -->

<!-- planned:config-migration-chain -->
#### UC-CFG-CAP-26: A registered project keeps its subscriptions across the unsubscribed default

```
Given a registered project whose configuration was written while an omitted block still meant subscribed
And that configuration declares no capability blocks
When the project configuration is loaded
Then the code, docs, and agents capabilities each resolve to enabled
And once a configuration migration run stores the document, it declares each of them enabled
```

#### UC-CFG-CAP-27: A linked worktree of a registered project resolves as its project

```
Given a registered project whose configuration was written while an omitted block still meant subscribed
And that configuration declares no capability blocks
And a linked worktree of that project whose copy of the configuration is equally old
When the capabilities are resolved inside that worktree by the runtime or by the installed plumbing
Then the code, docs, and agents capabilities each resolve to enabled
```

#### UC-CFG-CAP-28: A declaration the registries do not name claims nothing by omission

```
Given a repository whose teleclaude.yml declares the project tier and no capability blocks
And that declaration was written while an omitted block still meant subscribed
And the repository's root is not registered
When the capabilities are resolved by the runtime or by the installed plumbing
Then the code, docs, and agents capabilities each resolve to unsubscribed
And the git wrapper execs the real git binary without intercepting an agent session's invocation
```

#### UC-CFG-CAP-29: The plumbing resolves a registered declaration the migration list has not yet stored

```
Given a registered project whose stored teleclaude.yml carries no tier declaration
And that document has not passed the declaring migration
When an agent session invokes git inside that project
Then the installed plumbing resolves the project tier and the subscriptions the runtime resolves
And the invocation is not refused for a missing declaration
```

#### UC-CFG-CAP-30: Registration declares the subscriptions a document leaves undeclared

```
Given a project root that is not registered
And its configuration declares the code capability and neither the docs nor the agents capability
When an operator or agent registers that project
Then the code capability keeps its declared value
And the docs and agents capabilities are declared with values inferred from the repository's shape
```

#### UC-CFG-CAP-31: An installation advance makes the plumbing resolve again

```
Given the installed plumbing has kept its answer for a project's declaration
When canonical main advances with a change to the installation's code, or installation runs
Then the next git invocation in that project resolves the declaration through the runtime
```

#### UC-CFG-CAP-32: A slug worktree's plumbing answers from the worktree's own declaration

```
Given a slug worktree whose copy of teleclaude.yml declares capability subscriptions that differ from the owning checkout's
When an agent session invokes git inside that worktree
Then the installed plumbing decides from the worktree's own copy

Given a slug worktree that carries no teleclaude.yml
When an agent session invokes git inside that worktree
Then the git wrapper execs the real git binary without intercepting the invocation
```

#### UC-CFG-CAP-33: A capability resolved from the project's environment file resolves alike on both readers

```
Given a project whose code capability block takes its enabled value from a variable in the declaration's sibling .env
When the capabilities are resolved by the runtime or by the installed plumbing
Then both readers resolve the code capability to the value the .env holds
And after that value changes in the .env, the next git invocation decides from the new value
```
<!-- /planned:config-migration-chain -->


## Known caveats

- A project manifest key must be declared by the project overlay schema before
  it is written. An undeclared key fails configuration loading and does not
  become load-bearing later.
- Capability toggles gate _mechanisms_, not content: disabling `docs` in a
  repo that still contains snippet frontmatter leaves those files unsynced and
  is surfaced as drift by the quality-configuration assessment procedure.

<!-- planned-change:config-migration-chain -->
- The runtime and the installed plumbing agree on every declaration whose
  capability blocks carry unquoted boolean values. They part on one input: a
  block whose `enabled` value the runtime coerces from a quoted string or a
  number is refused by the plumbing, which reads only unquoted booleans. Both
  readers read only the tier and the capability blocks, so a declaration that
  fails validation elsewhere in the overlay keeps its capability answer on
  both; loading the full overlay still refuses it.
<!-- change:config-migration-chain -->
- The runtime's capability answer and the installed plumbing both read only a
  declaration's tier and capability blocks, so they answer alike for every
  declaration. A declaration whose tier and capability blocks are readable but
  which fails validation elsewhere in the overlay keeps its capability answer
  and keeps git working; loading the full overlay still refuses it.
- The first read after a file a kept answer was read from changes, or after the
  installation's code advances, pays one start of the installation's interpreter;
  every later read is served without one. An answer resolved in the same whole
  second as a change to one of its files is returned but not kept, because
  whole-second modification times cannot tell a later change within that second
  apart; the next read resolves again.
<!-- /planned-change:config-migration-chain -->


## See Also

- docs/project/design/architecture/checkpoint-system.md
- docs/project/procedure/checkpoint-overlay-projection.md
- docs/project/spec/domain/config.md
