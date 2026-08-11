---
description: 'telec sync validates authored snippet, artifact, and jobs-config source and always blocks on findings; deploy mode records best-effort provenance, builds indexes, and distributes runtime artifacts.'
visibility: 'public'
---

# Sync Pipeline Orchestration — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

`telec sync` is the operator-facing command that promotes git-tracked Source
into Deployed agent runtime outputs. Its responsibility is synchronization:
validate authored source shape, record best-effort provenance, rebuild derived
indexes, and distribute runtime artifacts. It does not mutate doc snippets in
response to todo delivery state; delivery-driven `delivered_by` reconciliation
belongs to the integration lifecycle before the delivery commit is made.

The sync pipeline is:

1. **Validate** — run snippet, artifact, and jobs-config validators.
2. **Record provenance** _(best-effort)_ — when a provenance back-end is
   configured, insert `delivered_by` memberships for audit. Back-end
   unavailability is caught and logged as a warning. This step never blocks
   phases 3–4.
3. **Build indexes** — write fresh derived doc indexes from source snippets.
4. **Distribute** — invoke the distribution step in deploy mode.

A deploy-mode run also registers the invoking project's durable root in the
project manifest when that project declares a non-empty `business.publishes` or
contains at least one direct `agents/skills/<name>/` folder. The domain
declaration publishes global docs; the skill folder publishes a global skill and
is itself the declaration — no separate capability or registration step exists.
The registered root is the canonical main checkout (a worktree resolves to its
owning checkout), and registration is idempotent. The read-only `--skip-deploy`
gate performs no registration.

Validation always blocks: any finding stops the pipeline and `telec sync` exits
non-zero — there is no warn-and-pass mode. Each flag skips one phase:

- `--skip-deploy` — validate only; return after validation with no index build,
  symlink repair, or distribution. The read-only gate for pre-commit / CI / lint;
  it must not mutate the host's agent-runtime dirs, and it still blocks on findings.
- `--skip-validation` — skip validation entirely and deploy without blocking.
  Hidden and role-gated to the docs watcher (live reload must never stall on a
  mid-edit state); the commit gate is the real validation contract. Not for agents.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

`telec sync` is the read-only source-validation command. It validates authored
snippet, agent-artifact, and jobs-config source as that invocation reads it, and
exits zero only when validation is clean. It performs no index build,
registration, provenance write, symlink repair, or runtime deployment.

Deploy mode runs the mutating phases in order:

1. **Validate** the source as the run reads it.
2. **Record provenance** on a best-effort basis.
3. **Build derived indexes and configuration outputs**.
4. **Distribute** the built artifacts to the runtime destinations.

`telec sync --deploy` is that path. The background watcher runs it as its normal
means of publishing; an operator may invoke it directly, which is exceptional
rather than routine. Validation findings abort before any mutating phase and
leave the previously published outputs intact. The former `--skip-deploy`
spelling remains a deprecated compatibility alias for the default
validation-only behavior during the migration; the watcher-only validation
bypass is removed.

Publication is not transactional against edits made while it runs. Waiting for
source activity to settle shows the source was quiet before publishing began; it
does not establish that validation and the later build read identical bytes.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

Validation findings are stdout text grouped by error code and reason; there is
no machine-readable output channel today.

## Canonical fields

Each per-project phase runs only when the project subscribes the capability that
owns it (`project/spec/feature/config/project-capability-manifest`). Snippet
validation, index building, and documentation publication run only under a
subscribed `docs`; agent-artifact transpilation and deployment run only under a
subscribed `agents`. A project subscribing neither still registers and still
converges its derived plumbing.

Capability projection runs on the mutating sync path only: it writes the
`.git` capability markers (the `onboarded` sentinel plus one per enabled
capability) and reconciles the docs filter driver (present iff `docs`) from the
declaration. `--skip-deploy` is read-only — it writes no marker state, installs
or withdraws no hooks or `.gitattributes` lines, and does not touch the driver.

The behavioral contract for this gating lives in
`project/spec/feature/config/project-capability-manifest` — `UC-CFG-CAP-17` (an unsubscribed
`docs` capability leaves the snippet pipeline idle) and `UC-CFG-CAP-18` (an unsubscribed `agents`
capability leaves artifact distribution idle). Those scenarios are the single inventory for this
behavior; this spec references them rather than restating them.

### Use cases

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

```
Scenario: Full sync on a clean Mother project checkout
  Given the project source is git-tracked and validates cleanly
  When the operator runs telec sync
  Then snippet, artifact, and jobs-config validators run once
  And the index-build phase produces a fresh index
  And broken or self-pointing tracked docs symlinks are repaired
  And the distribution step is invoked in deploy mode
And the run exits zero
```

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

```gherkin
Scenario: Default sync validates without deployment
  Given a project with authored snippet, artifact, and jobs-config source
  When telec sync is invoked
  Then the validators run against the source as that invocation reads it
  And no index, manifest, provenance, symlink, configuration, or runtime output is mutated
  And the command exits zero only when validation is clean
```

```gherkin
Scenario: Deploy mode validates before it mutates
  Given a project whose authored source validates cleanly
  When telec sync --deploy is invoked
  Then validation runs before any mutating phase
  And indexes and derived configuration are built
  And runtime artifacts are rebuilt and distributed
  And the command exits zero
```

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

```
Scenario: --skip-deploy validates but produces no derived outputs
  Given the operator wants to validate without deploying
  When telec sync --skip-deploy is invoked
  Then validators run once
  And no index build, symlink repair, or distribution step runs
And the run exits zero only when validation is clean
```

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

```gherkin
Scenario: Deprecated --skip-deploy remains validation-only
  Given a caller still invokes telec sync --skip-deploy during the compatibility window
  When the command runs
  Then it behaves exactly like default telec sync
  And it emits a deprecation notice naming telec sync as the replacement
  And it exits zero only when validation is clean
```

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

```
Scenario: Validation findings always block
  Given snippet, artifact, or jobs-config validation reports a finding
  When telec sync (with or without --skip-deploy) is invoked
  Then the findings are printed grouped by error code and reason
  And the pipeline aborts before any deploy
And the run exits non-zero
```

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

```gherkin
Scenario: Validation findings always block
  Given snippet, artifact, or jobs-config validation reports a finding
  When default telec sync or telec sync --deploy is invoked
  Then the findings are printed grouped by error code and reason
  And explicit deploy aborts before any mutating phase
  And the command exits non-zero
```

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

```
Scenario: The docs watcher bypasses validation to live-reload
  Given the docs watcher authorizes the hidden --skip-validation flag
  When telec sync --skip-validation is invoked
  Then validation is skipped entirely
  And the pipeline records provenance, builds indexes, and distributes
  And the run never blocks on source validity
```

```
Scenario: A non-watcher caller is rejected from bypassing validation
  Given a caller that is not the docs watcher
  When it invokes telec sync --skip-validation
  Then the command is rejected and exits non-zero
And no deploy occurs
```

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

```gherkin
Scenario: The watcher publishes only after validation passes
  Given a relevant source change triggers the background watcher
  When source activity settles and the watcher begins its pass
  Then the watcher validates the source before any mutating phase
  And valid source is built and distributed
  And invalid source emits a watcher failure event and leaves the previously published outputs in place
  And the next relevant source change is eligible for a fresh attempt
```

```gherkin
Scenario: Validation bypass is unavailable
  Given any caller requests deployment without source validation
  When the sync boundary receives that request
  Then the request is rejected
  And no build or deployment occurs
```

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

```
Scenario: Provenance back-end is unavailable
  Given a provenance back-end is configured
  And the back-end is unreachable, misauthenticated, or out of date
  When telec sync --deploy runs
  Then the provenance recording step logs a warning
  And the pipeline continues to build indexes and distribute artifacts
  And sync returns success
```

```
Scenario: Delivery completes before sync
  Given an integration delivery staged snippet lifecycle reconciliation in its merge commit
  When telec sync runs after the delivery
  Then sync validates the already-mutated source
  And sync performs no additional source markdown mutations
```

```
Scenario: UC-SPO1 A publishing sync registers the publisher so its domain is universally valid
  Given a project declares a domain in business.publishes in its own teleclaude.yml
  And that project's root is not yet in the project manifest
  When the operator runs telec sync in deploy mode
  Then the project's durable root is registered in the manifest
  And the declared domain joins the set of valid domains platform-wide without a separate telec projects init
  And running telec sync again does not add a duplicate manifest entry
```

```
Scenario: UC-SPO2 The read-only gate registers no publisher
  Given a project declares a domain in business.publishes
  And that project's root is not in the project manifest
  When telec sync --skip-deploy is invoked
  Then no manifest registration occurs
  And the manifest is left unchanged
```

```
Scenario: UC-SPO3 A non-publishing project registers no root
  Given a project declares no domains in business.publishes
  And contains no direct agents/skills/<name>/ folder
  And that project's root is not in the project manifest
  When the operator runs telec sync in deploy mode
  Then no manifest registration occurs
  And the manifest is left unchanged
```

```
Scenario: UC-SPO5 A global skill folder registers its publisher by existence
  Given a project declares no domains in business.publishes
  And contains a direct agents/skills/<name>/ folder
  And that project's root is not yet in the project manifest
  When the operator runs telec sync in deploy mode
  Then the project's durable root is registered in the manifest
  And the named skill joins global skill composition without a configuration capability
  And running telec sync again does not add a duplicate manifest entry
```

#### UC-SPO4: Deploy-mode sync is refused from a slug worktree

```
Scenario: UC-SPO4 Deploy-mode sync is refused from a slug worktree
  Given telec sync runs in deploy mode from a slug worktree (trees/<slug>, not trees/_integration)
  When the pipeline starts
  Then it exits non-zero with an error that docs deployment is not allowed from a slug worktree
  And no validation, index build, symlink repair, or distribution step runs
  And a --skip-deploy run, and deploy-mode sync from the main checkout or the integration worktree, are unaffected
```

### Cross-context references

- **workflow / integration** — own todo delivery state and delivery-time
  `delivered_by` reconciliation.
- **config** — supplies project root and Mother-project resolution consumed by
  the distribution step.
- **agent_runtime** — phase 4's distribution step deploys to the agent runtime
  boundary.

## Known caveats

- Sync is idempotent at the source markdown layer: it writes the derived,
  gitignored `index.yaml` indexes into the source tree and each published
  domain's `domain-baseline-bundle.md` into the deployed root
  `~/.teleclaude/docs/<domain>/` (not the source tree), but it must not mutate
  authored `docs/**/*.md` snippets.
- Provenance recording is best-effort: back-end availability is not required
  for sync to complete. When the back-end is unavailable, provenance rows are
  skipped and a warning is emitted. Drift between sync runs and the
  provenance store is expected until the back-end is healthy again.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- `--skip-deploy` exits before index build and symlink repair. Broken tracked
  symlinks may therefore remain broken until a full sync runs.
- `--skip-validation` deploys unvalidated source; it is reserved for the docs
  watcher's live reload, where the commit gate remains the validation contract.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Default sync and its deprecated `--skip-deploy` alias are read-only. Derived
  outputs may remain behind source until the watcher or an explicit deploy run
  publishes them.
- No deployment path bypasses validation. A watcher finding leaves the
  previously published outputs in place and retries only after another relevant
  source change.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Project bootstrap (`telec projects init` / `onboard`, via `sync_bootstrap`)
  validates and reports findings without blocking, then deploys — a human-run,
  one-time setup path distinct from the always-blocking `telec sync` command.
  The commit gate remains the validation contract for ongoing work.
- The distribution step is optional in stripped-down deployments because a
  missing distribution entrypoint silently skips phase 4.
- The v1 CLI namespace is `telec sync`. The v2 target is `telec context sync`.
