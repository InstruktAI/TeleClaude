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
  Owns `telec code test` / `format` / `install`, the code checks of
  `telec code lint` and the commit gate (the project's native `make lint` and
  TeleClaude's code rules), git hooks, worktree rules, and the checkpoint
  toolchain and log-check bindings. `test`, `format`, and `install` refuse
  cleanly ("not a code project") when disabled. `telec code lint`, the
  sealed-commit surface (`telec code commit` / `add`), and the git wrapper's
  commit interception are not owned by `code` alone — they follow `code ∨ docs`
  (see the derivation rules).
- `docs: { enabled }` — the snippet pipeline: the `docs/**` publication base
  binding, the `.gitattributes` docs filters, and snippet validation, indexing,
  and publication. Snippet validation is the documentation check of
  `telec code lint` and the commit gate.
- `agents: { enabled }` — agent artifacts: the `agents/**`-family base binding,
  artifact transpilation and deployment, and artifact validation within
  `telec code lint` and the commit gate.

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
  or the project declares at least one custom path binding; an event binding
  alone does not activate it. Otherwise `agent_stop` passes through with no
  timeline extraction and no evidence scanning.

- The commit obligation is active iff `code ∨ docs` is enabled.
- `telec code lint` and the commit gate run iff `code ∨ docs` is enabled at a
  file's owning home, over that home's changed files: staged files at the
  commit gate, declared or named files for a scoped lint, and every file of the
  home that git does not ignore for a full run. Each capability contributes only its own
  checks — `code` the native toolchain and TeleClaude's code rules, `docs`
  snippet validation, `agents` artifact validation — so a home without `code`
  never runs a code check. A full run widens the files, never the checks.
- A global, person, or company home declares no capability blocks. For these
  checks it counts as `docs` and `agents` by its kind
  (`local/projects/teleclaude/spec/feature/config/tier-permissions`), and never as
  `code`.
- Every staged `teleclaude.yml` is validated at the commit gate as that one
  file, through the same pipeline that loads it: migrated, its references
  resolved from the environment file beside it on this computer, and its
  schema and declared field relationships judged. Whether this computer holds
  the values its role needs is its readiness, which the commit gate does not
  judge (`local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`).
  This holds in every home whose commit-gate hooks are installed, whatever that
  home subscribes. No other configuration file is validated. In a home that enables neither `code` nor
  `docs`, declaration validation is the gate's only check, and that home still
  raises no commit obligation. A declaration that fails validation refuses the
  commit, so committed state, which every consumer derives from, never holds an
  invalid declaration (ADR-0108).
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
  the git hooks and the git wrapper — resolves the toggles through the runtime's
  own reading of the repository root's own declaration: brought to its current
  shape by the configuration migration list
  (`local/projects/teleclaude/spec/feature/config/document-migration`); and its tier and each
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
  `local/projects/teleclaude/design/code-commit`. Because the declaration is a file the project
  tracks, a clone carries the project's real capability state before any
  TeleClaude command has run against it.

- A capability toggle never edits, removes from, or truncates a file the project
  tracks. The only capability plumbing in the project's tracked tree is the
  `.gitattributes` docs-filter line, written once — additively, at onboard, with
  the human in the loop — and never touched again. Enabling or disabling `docs`
  toggles the filter driver in `.git/config` (TeleClaude's own, untracked); with
  the driver absent the `.gitattributes` line is inert, because git treats a
  filter attribute whose driver is undefined as a no-op. Converging the installed
  driver and hooks to this declaration is reconciliation's act, contracted in
  `local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`; this
  declaration is what that act reads. The safety guarantee — TeleClaude never
  rewrites a project-owned file on a toggle — holds by construction, not by a
  runtime guard.
- Onboard is the one-time additive install: it writes the `.gitattributes` line,
  then converges the project's plumbing to the declaration it has just written.
  After onboard, a toggle takes effect on the plumbing's next invocation because
  the plumbing reads the declaration itself; what that convergence installs,
  withdraws, or refreshes is contracted in
  `local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`. Neither path
  ever rewrites a project-tracked file.

- A repository carrying no `teleclaude.yml` is not a TeleClaude target: no
  non-adopting path — a sync, the checkpoint engine, the git wrapper — installs
  or reads anything for it, and it is left byte-for-byte untouched. The sole
  exception is explicit adoption: `telec config project adopt` creates
  the `teleclaude.yml` and its inferred declaration — that is the sanctioned act
  that turns a plain repository into a target. Carrying no manifest and carrying
  a broken one are different states: the first is simply not a target, while the
  second is an adopted project whose declaration cannot be read, and that surfaces
  as a failure rather than resolving to any capability state.
- The project's `teleclaude.yml`, `.env`, and equivalent native files are
  project-owned and are never removed, superseded, or displaced.
- A capability block that is absent, or present without an `enabled` value,
  resolves to unsubscribed: only an explicit value claims a capability.
  Registration declares every capability the document leaves undeclared, with
  the value inferred from repo shape, and assessment refines the declarations. A
  registered project whose declaration was written while an omitted block still
  meant subscribed keeps those subscriptions: the configuration migration list
  brings its declaration forward with each of them written explicitly, and the
  same holds for its linked worktrees' copies. A declaration the registries do
  not name gains no subscription from that migration.

### Use cases

#### UC-CFG-CAP-1: An operator can leave a project without capability automation

```
Given an operator wants TeleClaude tooling to stay inactive for a project
When no project capabilities are declared
Then code, docs, and agent-artifact mechanisms remain unsubscribed for that project
```

#### UC-CFG-CAP-2: An operator selects the project capabilities

```
Given an operator wants docs and agent-artifact tooling but no code toolchain for a project
When they declare docs and agents enabled and code disabled
Then the project subscribes to docs and agents but not code
And the selected capabilities take effect on their next invocation
```

#### UC-CFG-CAP-3: An operator can diagnose unreadable capability configuration

```gherkin
Scenario: An unreadable project manifest does not invent capability state
  Given an adopted project has a `teleclaude.yml` the runtime cannot read
  When the project capabilities are needed
  Then the read failure is surfaced without substituting capability state

Scenario: An unreadable capability block refuses a git invocation
  Given an adopted project has a capability block whose `enabled` value is not a boolean
  When installed plumbing resolves the project capabilities
  Then the git invocation is refused with a diagnostic naming the manifest and block
  And no capability state is substituted
```

#### UC-CFG-CAP-4: A subscribed capability activates the checkpoint engine

#### UC-CFG-CAP-5: No subscription and no declared binding yields silence

#### UC-CFG-CAP-6: A declared path binding alone activates the engine

#### UC-CFG-CAP-7: Base bindings attach per subscribed capability

#### UC-CFG-CAP-8: A project subscribing neither code nor docs raises no commit obligation

#### UC-CFG-CAP-9: An operator can lint docs in a docs-only project

```
Given a project subscribes to docs but not code
When an operator runs `telec code lint` for a changed docs file
Then the documentation is validated without running code-toolchain checks
```

#### UC-CFG-CAP-10:

#### UC-CFG-CAP-11:

#### UC-CFG-CAP-12: An operator can change a capability without changing project files

```
Given an operator changes a project's capability selection
When the declaration is saved and the plumbing next runs
Then no project-tracked file other than the declaration is changed
And capability state remains in that declaration
```

#### UC-CFG-CAP-13:

#### UC-CFG-CAP-14: A non-adopting path never touches a manifest-less repository

#### UC-CFG-CAP-15: A changed declaration takes effect with no projection pass

#### UC-CFG-CAP-16: The installed plumbing answers a repeated read without an interpreter

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

#### UC-CFG-CAP-20: An operator's clone honors the project's capability selection

```
Given an operator clones a project whose declaration leaves code and docs unsubscribed
When they invoke git inside the clone before any TeleClaude command has run there
Then the clone honors those capability choices
```

#### UC-CFG-CAP-21: The plumbing reads a hand-authored inline declaration

#### UC-CFG-CAP-22:

#### UC-CFG-CAP-24: An unreadable capability block refuses the git invocation

#### UC-CFG-CAP-25: A capability block without an enabled value resolves to unsubscribed

#### UC-CFG-CAP-26: A registered project keeps its subscriptions across the unsubscribed default

#### UC-CFG-CAP-27: A linked worktree of a registered project resolves as its project

```
Given a registered project whose configuration was written while an omitted block still meant subscribed
And that configuration declares no capability blocks
And a linked worktree of that project whose copy of the configuration is equally old
When the capabilities are resolved inside that worktree by the runtime or by the installed plumbing
Then the code, docs, and agents capabilities each resolve to enabled
```

#### UC-CFG-CAP-28: A declaration the registries do not name claims nothing by omission

#### UC-CFG-CAP-29: The plumbing resolves a registered declaration the migration list has not yet stored

#### UC-CFG-CAP-30: An operator onboards a project with inferred capabilities

```
Given an operator onboards a project whose configuration declares only the code capability
When the project is registered
Then the code selection is preserved and undeclared capabilities are inferred from repository shape
```

#### UC-CFG-CAP-31: An installation advance makes the plumbing resolve again

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

#### UC-CFG-CAP-34: A staged declaration that fails validation refuses the commit

#### UC-CFG-CAP-35: An event binding alone leaves the engine silent

## Known caveats

- A project manifest key must be declared by the project overlay schema before
  it is written. An undeclared key fails configuration loading and does not
  become load-bearing later.
- Capability toggles gate _mechanisms_, not content: disabling `docs` in a
  repo that still contains snippet frontmatter leaves those files unsynced and
  is surfaced as drift by the quality-configuration assessment procedure.

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

## See Also

- docs/local/design/architecture/checkpoint-system.md
- docs/local/procedure/checkpoint-overlay-projection.md
- docs/local/spec/domain/config.md
