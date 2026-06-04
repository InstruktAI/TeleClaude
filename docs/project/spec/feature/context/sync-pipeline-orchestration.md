---
id: 'project/spec/feature/context/sync-pipeline-orchestration'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by: [integrate-deliveredby-flip]
description: 'telec sync validates source, records best-effort provenance, builds indexes, and distributes artifacts under --validate-only / --warn-only semantics.'
---

# Sync Pipeline Orchestration — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

`telec sync` is the operator-facing command that promotes git-tracked Source
into Deployed agent runtime outputs. Its v1 responsibility is synchronization:
validate authored source shape, record best-effort provenance, rebuild derived
indexes, and distribute runtime artifacts. It does not mutate doc snippets in response to roadmap
delivery state; delivery-driven `delivered_by` reconciliation belongs to the
integration lifecycle before the delivery commit is made.

The sync pipeline is:

1. **Validate** — run snippet, artifact, and jobs-config validators.
2. **Record provenance** _(best-effort)_ — if `DATABASE_URL` is set, insert
   `delivered_by` memberships into `workflow.snippet_provenance` for v2 audit.
   v2 postgres failures (container down, credential mismatch, missing migration)
   are caught and logged as warnings. This step never blocks phases 3–4.
3. **Build indexes** — write fresh derived doc indexes from source snippets.
4. **Distribute** — invoke `scripts/distribute.py` with `--deploy` and the
   optional `--warn-only` flag.

Two flags govern scope and failure semantics:

- `--validate-only` — return after validation; no index build, symlink repair,
  or distribute subprocess.
- `--warn-only` — print validation findings without exiting non-zero, and
  forward the flag into the distribute subprocess.

Validation findings are stdout text grouped by error code and reason; there is
no machine-readable output channel in v1.

## Canonical fields

### Use cases

```
Scenario: Full sync on a clean Mother project checkout
  Given the project source is git-tracked and validates cleanly
  When the operator runs telec sync
  Then snippet, artifact, and jobs-config validators run once
  And build_all_indexes produces a fresh index
  And broken or self-pointing tracked docs symlinks are repaired
  And scripts/distribute.py is invoked with --deploy
  And the run exits zero
```

```
Scenario: Validation-only run exits before derived outputs
  Given the operator wants to lint without deploying
  When telec sync --validate-only is invoked
  Then validators run once
  And no index build, symlink repair, or distribute subprocess runs
```

```
Scenario: Warn-only sync with non-fatal validation findings
  Given snippet validation reports a non-fatal finding
  When telec sync --warn-only is invoked
  Then validation findings are printed grouped by error code and reason
  And the validation phase does not abort the pipeline
  And --warn-only is forwarded to the distribute subprocess
  And the sync proceeds through index build and distribute
```

```
Scenario: Distribute subprocess fails under --warn-only and the failure is suppressed
  Given telec sync --warn-only is invoked
  And scripts/distribute.py exits non-zero due to a runtime error
  When subprocess.run is invoked with check=not warn_only
  Then the non-zero exit is not raised as CalledProcessError
  And sync returns True regardless of the subprocess exit code
```

```
Scenario: v2 postgres is unavailable during provenance recording
  Given DATABASE_URL is set
  And the v2 postgres container is down, credentials are wrong, or migration 0002 is missing
  When telec sync runs
  Then the provenance recording step logs a warning to stderr
  And the pipeline continues to build indexes and distribute artifacts
  And sync returns True
```

```
Scenario: Delivery completes before sync
  Given an integration delivery staged snippet lifecycle reconciliation in its merge commit
  When telec sync runs after the delivery
  Then sync validates the already-mutated source
  And sync performs no additional source markdown mutations
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/misc.py` — `_handle_sync()` parses
  `--validate-only` and `--warn-only`.
- `teleclaude/sync.py` — validation, index build, symlink repair, and
  distribute subprocess orchestration.
- `teleclaude/docs_index.py` — derived index generation.
- `teleclaude/docs_reconcile.py` — lifecycle reconciliation primitives used by
  lifecycle callers, not by sync.
- `teleclaude/services/maintenance_service.py` — removed-Todo retention cleanup
  uses the purge-time planning entrypoint before committing snippet changes and
  hard-deleting rows.

### Cross-context references

- **workflow / integration** — own todo delivery state and delivery-time
  `delivered_by` reconciliation.
- **config** — supplies project root and Mother-project resolution consumed by
  the distribute subprocess.
- **agent_runtime** — phase 4's distribute step deploys to the agent runtime
  boundary.

## Known caveats

- Sync is idempotent at the source markdown layer: it may update generated
  indexes and deployed artifacts, but it must not mutate authored
  `docs/**/*.md` snippets for delivery-state reasons.
- Provenance recording is best-effort: v2 postgres availability is not required
  for sync to complete. When v2 postgres is unavailable, provenance rows are
  skipped and a warning is emitted to stderr. Drift between v1 sync
  runs and v2 provenance store is expected until v2 postgres is healthy again.
- `--validate-only` exits before index build and symlink repair. Broken tracked
  symlinks may therefore remain broken until a full sync runs.
- `--warn-only` is risky because distribute failures are suppressed when
  `check=False`.
- The distribute step is optional in stripped-down deployments because a
  missing `scripts/distribute.py` silently skips phase 4.
- v1 CLI namespace is `telec sync`. v2 target is `telec context sync`.
