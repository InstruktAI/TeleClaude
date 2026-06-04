---
id: 'project/spec/feature/context/sync-pipeline-orchestration'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
delivered_by: [integrate-deliveredby-flip]
description: 'telec sync validates source, records best-effort provenance, builds indexes, and distributes artifacts under --validate-only / --warn-only semantics.'
---

# Sync Pipeline Orchestration — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

`telec sync` is the operator-facing command that promotes git-tracked Source
into Deployed agent runtime outputs. Its responsibility is synchronization:
validate authored source shape, record best-effort provenance, rebuild derived
indexes, and distribute runtime artifacts. It does not mutate doc snippets in
response to todo delivery state; delivery-driven `delivered_by` reconciliation
belongs to the integration lifecycle before the delivery commit is made.

The sync pipeline is:

1. **Validate** — run snippet, artifact, and jobs-config validators.
2. **Record provenance** *(best-effort)* — when a provenance back-end is
   configured, insert `delivered_by` memberships for audit. Back-end
   unavailability is caught and logged as a warning. This step never blocks
   phases 3–4.
3. **Build indexes** — write fresh derived doc indexes from source snippets.
4. **Distribute** — invoke the distribution step in deploy mode, optionally
   in warn-only mode.

Two flags govern scope and failure semantics:

- `--validate-only` — return after validation; no index build, symlink repair,
  or distribution step.
- `--warn-only` — print validation findings without exiting non-zero, and
  forward the flag into the distribution step.

Validation findings are stdout text grouped by error code and reason; there is
no machine-readable output channel today.

## Canonical fields

### Use cases

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

```
Scenario: Validation-only run exits before derived outputs
  Given the operator wants to lint without deploying
  When telec sync --validate-only is invoked
  Then validators run once
  And no index build, symlink repair, or distribution step runs
```

```
Scenario: Warn-only sync with non-fatal validation findings
  Given snippet validation reports a non-fatal finding
  When telec sync --warn-only is invoked
  Then validation findings are printed grouped by error code and reason
  And the validation phase does not abort the pipeline
  And --warn-only is forwarded to the distribution step
  And the sync proceeds through index build and distribute
```

```
Scenario: Distribution step fails under --warn-only and the failure is suppressed
  Given telec sync --warn-only is invoked
  And the distribution step exits non-zero due to a runtime error
  When the pipeline checks the distribution step's exit conditionally on --warn-only
  Then the non-zero exit is not raised as an error
  And sync returns success regardless of the distribution step's exit code
```

```
Scenario: Provenance back-end is unavailable
  Given a provenance back-end is configured
  And the back-end is unreachable, misauthenticated, or out of date
  When telec sync runs
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

### Cross-context references

- **workflow / integration** — own todo delivery state and delivery-time
  `delivered_by` reconciliation.
- **config** — supplies project root and Mother-project resolution consumed by
  the distribution step.
- **agent_runtime** — phase 4's distribution step deploys to the agent runtime
  boundary.

## Known caveats

- Sync is idempotent at the source markdown layer: it may update generated
  indexes and deployed artifacts, but it must not mutate authored
  `docs/**/*.md` snippets for delivery-state reasons.
- Provenance recording is best-effort: back-end availability is not required
  for sync to complete. When the back-end is unavailable, provenance rows are
  skipped and a warning is emitted. Drift between sync runs and the
  provenance store is expected until the back-end is healthy again.
- `--validate-only` exits before index build and symlink repair. Broken tracked
  symlinks may therefore remain broken until a full sync runs.
- `--warn-only` is risky because distribution-step failures are suppressed.
- The distribution step is optional in stripped-down deployments because a
  missing distribution entrypoint silently skips phase 4.
- The v1 CLI namespace is `telec sync`. The v2 target is `telec context sync`.
