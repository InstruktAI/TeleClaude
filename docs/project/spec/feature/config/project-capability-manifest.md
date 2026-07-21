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
  Owns the sealed-commit surface (`telec code *`), quality lanes, git hooks,
  the tmux git wrapper, worktree rules, and the checkpoint toolchain and
  log-check bindings. `telec code *` refuses cleanly ("not a code project")
  when disabled.
- `docs: { enabled }` — the snippet pipeline: the `docs/** → telec sync` base
  binding, the `.gitattributes` docs filters, and the pipeline itself. An
  unsubscribed project has no snippet validated, indexed, or published for it.
- `agents: { enabled }` — agent artifacts: the `agents/**`-family base binding
  (`telec sync` + `telec sessions restart self`) and artifact distribution
  itself. An unsubscribed project has no artifact transpiled or deployed for it.

Each capability gates both its checkpoint binding and the mechanism it names, so
an unsubscribed capability leaves the pipeline it owns idle for that project
while every other subscribed pipeline continues to run.

Task tracking (`telec todo`, `telec bugs`) carries no toggle: a manifest's
existence is the subscription. A data repository holds a `teleclaude.yml` for
exactly this capability, and a code project needs todos for its lifecycle, so
no repo can meaningfully disable it.

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
- Convergence removes only TeleClaude-authored plumbing, and never a
  project-owned file. A project is functionally agnostic of TeleClaude;
  TeleClaude adopts a project by adding configuration to it, and the project's
  own files remain the project's. Where TeleClaude writes into a file the
  project owns — the `.gitattributes` filter lines, a git hook the project also
  uses, any shared file — convergence withdraws only the lines TeleClaude
  authored and leaves the file in place. A hook file whose content no longer
  matches what TeleClaude authored is left untouched and surfaced as drift. A
  convergence pass that deletes or truncates a project-owned file is a defect,
  not a capability toggle.
- Convergence acts only on a project that carries a `teleclaude.yml`. The
  manifest's presence is the subscription, so a repository without one is not a
  TeleClaude target and a convergence pass leaves it byte-for-byte untouched.
  Resolving an unreadable declaration to all-subscribed applies only to a
  project already carrying a manifest; it never adopts a repository that carries
  none.
- Convergence reports its outcome rather than degrading silently. A pass that
  could not install plumbing a subscribed capability requires, or that found a
  project-modified artifact it declined to touch, reports that in its outcome so
  the invoking surface can surface it. A pass never reports success over
  plumbing it did not converge.
- The project's `teleclaude.yml` is itself project-owned and is never removed by
  any convergence pass. Its presence is what makes the project a target for
  TeleClaude capabilities at all. `.env` and equivalent native project files are
  kept for human reference and are never superseded or displaced by
  database-backed configuration.
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

#### UC-CFG-CAP-8: The commit obligation follows code or docs

```
Given a project subscribing neither code nor docs
When a commit is recorded on the canonical branch
Then no commit obligation is raised for that commit
```

#### UC-CFG-CAP-9: The code surface refuses cleanly when unsubscribed

```
Given a project that does not subscribe the code capability
When an operator invokes a telec code subcommand
Then the command refuses with a message naming the capability that gates it
And the command reports failure rather than attempting the underlying toolchain
```

#### UC-CFG-CAP-10: Convergence installs plumbing for a subscribed capability

```
Given a project subscribing docs and code whose derived plumbing is missing
When a convergence pass runs
Then the docs filter lines TeleClaude owns are present
And the git hooks TeleClaude owns are installed
```

#### UC-CFG-CAP-11: Disabling a capability withdraws only TeleClaude's own lines

```
Given a project whose docs capability has been disabled
And whose .gitattributes carries both TeleClaude filter lines and lines the project authored
When a convergence pass runs
Then the TeleClaude filter lines are withdrawn
And every line the project authored remains unchanged
And the .gitattributes file itself remains present
```

#### UC-CFG-CAP-12: A project-modified hook is left untouched and surfaced as drift

```
Given a project whose code capability has been disabled
And whose installed git hook no longer matches the content TeleClaude authored
When a convergence pass runs
Then the hook file is left in place unmodified
And the convergence outcome reports that hook as diverged
And the divergence is reported rather than resolved by removal
```

#### UC-CFG-CAP-13: Convergence never removes a project-owned file

```
Given a project with every capability disabled
When a convergence pass runs
Then the project's configuration file remains present
And no file the project owns is deleted or truncated
```

#### UC-CFG-CAP-14: Convergence is idempotent in both directions

```
Given a project whose plumbing already matches its declaration
When a convergence pass runs twice in succession
Then the second pass changes nothing that the first pass left
And the resulting plumbing state is identical after each pass
```

#### UC-CFG-CAP-15: A repository carrying no manifest is never adopted

```
Given a repository that carries no teleclaude.yml
When a convergence pass runs for that repository
Then no git hook is installed
And no filter line is written
And the repository is left byte-for-byte unchanged
```

#### UC-CFG-CAP-16: Changing a toggle during assessment converges immediately

```
Given a project whose assessment changes a capability from subscribed to unsubscribed
When that assessment completes
Then a convergence pass has run for the project
And the derived plumbing matches the newly written declaration
```

#### UC-CFG-CAP-17: Plumbing that could not be installed is reported, never assumed

```
Given a project subscribing the code capability
And a required hook source that cannot be installed
When a convergence pass runs
Then the convergence outcome reports the plumbing that was not installed
And the pass does not report success for that plumbing
```

#### UC-CFG-CAP-18: An unsubscribed docs capability leaves the snippet pipeline idle

```
Given a project that does not subscribe the docs capability
When the sync pipeline runs for that project
Then no snippet under docs/ is validated, indexed, or published for it
And the pipeline's other subscribed work still runs
```

#### UC-CFG-CAP-19: An unsubscribed agents capability leaves artifact distribution idle

```
Given a project that does not subscribe the agents capability
When the sync pipeline runs for that project
Then no agent artifact is transpiled or deployed for it
And the pipeline's other subscribed work still runs
```

#### UC-CFG-CAP-20: A starting session converges the project it starts in

```
Given a subscribed project whose derived plumbing has drifted from its declaration
When an agent session starts in that project
Then the plumbing converges to the declaration
And the session's own startup is not delayed waiting for that convergence
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
