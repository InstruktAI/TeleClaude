---
id: 'project/spec/feature/context/sync-pipeline-orchestration'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'telec sync orchestrates validate, reconcile + re-validate, and distribute phases, governed by --validate-only and --warn-only flags.'
---

# Sync Pipeline Orchestration — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

`telec sync` is the operator-facing single command that promotes
git-tracked Source into Deployed agent runtime outputs. It runs a
three-phase pipeline:

1. **Validate** — load the roadmap status map, then run snippet,
   artifact, and jobs-config validators with
   `enforce_delivered_drift=validate_only`. On `--validate-only`, this
   pass is the only validation pass; the run returns immediately after
   it, BEFORE reconciliation, index build, symlink repair, and
   distribute.
2. **Reconcile + re-validate** (full sync only) — flip delivered
   snippets to `actual` via `reconcile_snippet_status()`, then re-run
   snippet validation with `enforce_delivered_drift=True`.
3. **Distribute** — invoke `scripts/distribute.py` as a subprocess with
   `--deploy` (and optional `--warn-only`). Full sync ALWAYS passes
   `--deploy`; there is no `telec sync` no-deploy mode.

Two flags govern scope and failure semantics:

- `--validate-only` — return after the first validation pass; no
  reconciliation, no index build, no symlink repair, no distribute.
- `--warn-only` — print validation findings without exiting non-zero,
  and forward the flag into the distribute subprocess. The subprocess
  is invoked with `check=not warn_only`, so under `--warn-only` a
  non-zero distribute exit is **suppressed** rather than raised.

Validation findings are stdout text grouped by error code and reason;
there is no machine-readable output channel in v1.

The delivered-snippet reconciliation engine is shared. `telec sync` is the
full-sync caller that clears delivered drift after a slug reaches
`status=delivered`; the removed-Todo maintenance sweep is the retention caller
that removes hard-purged slugs from `delivered_by` before deleting the retained
roadmap row.

## Canonical fields

### Use cases

```
Scenario: Full sync on a clean Mother project checkout
  Given the project source is git-tracked and validates cleanly
  When the operator runs telec sync
  Then phase 1 validators run with enforce_delivered_drift=False
  And phase 1b reconcile flips delivered snippets to actual
  And phase 1b re-validates with enforce_delivered_drift=True
  And build_all_indexes produces a fresh index
  And broken or self-pointing tracked docs symlinks are repaired
  And scripts/distribute.py is invoked with --deploy
  And the run exits zero
```

```
Scenario: Validation-only run exits before reconciliation
  Given the operator wants to lint without deploying
  When telec sync --validate-only is invoked
  Then phase 1 validators run with enforce_delivered_drift=True
  And the run returns at sync.py:64-65 after that first pass
  And reconcile_snippet_status is NOT invoked
  And no second validation pass runs
  And no index build, symlink repair, or distribute subprocess runs
```

```
Scenario: Warn-only sync with non-fatal validation findings
  Given snippet validation reports a non-fatal finding
  When telec sync --warn-only is invoked
  Then validation findings are printed grouped by error code and reason
  And the validation phase does not abort the pipeline
  And --warn-only is forwarded to the distribute subprocess
  And the sync proceeds through reconcile, index build, and distribute
```

```
Scenario: Distribute subprocess fails under --warn-only and the failure is suppressed
  Given telec sync --warn-only is invoked
  And scripts/distribute.py exits non-zero due to a runtime error
  When subprocess.run is invoked with check=not warn_only (which is False here)
  Then the non-zero exit is NOT raised as CalledProcessError
  And sync() returns True regardless of the subprocess exit code
  And the operator may see a "silent success" — the only evidence of failure is the subprocess's own stdout/stderr
```

```
Scenario: Roadmap delivery during sync
  Given a slug is marked delivered during the sync run
  When the roadmap status map was already loaded at phase 1 start
  Then the in-flight delivery does not affect this sync
  And the next sync picks up the new delivery and reconciles its snippets
```

```
Scenario: Removed-row purge reuses the reconcile engine outside sync
  Given an expired removed Todo still appears in a snippet's delivered_by list
  When routine maintenance hard-purges the retained row
  Then the maintenance sweep plans and commits the delivered_by update through the shared reconcile engine
  And telec sync remains responsible only for full-sync delivered-drift reconciliation
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/misc.py:93-112` — `_handle_sync()` parses `--validate-only` and `--warn-only`.
- `teleclaude/cli/telec/handlers/misc.py:53-59` — `_run_sync()` delegate.
- `teleclaude/sync.py:28-101` — `sync()` three-phase orchestrator.
- `teleclaude/sync.py:42` — `build_roadmap_status_map()` load (once per run).
- `teleclaude/sync.py:45-52` — phase 1 validators (`validate_all_snippets`, `validate_all_artifacts`, `validate_jobs_config`).
- `teleclaude/sync.py:53-65` — error printing and `--validate-only` early exit.
- `teleclaude/sync.py:68, 77-81` — phase 1b reconcile + re-validate with `enforce_delivered_drift=True`.
- `teleclaude/sync.py:90-95` — `build_all_indexes()` and symlink repair.
- `teleclaude/sync.py:97-99, 104-122` — distribute subprocess invocation with `check=not warn_only`.
- `teleclaude/sync.py:124-160` — `_repair_broken_docs_links()` over the hardcoded tracked-docs tuple including `docs/global/baseline.md`.
- `teleclaude/sync.py:163-202` — `_print_findings()` text grouping.
- `teleclaude/docs_reconcile.py:34-41` — `SnippetWriteResult` carries purge-time write plans for callers that must stage and commit exact snippet pathspecs.
- `teleclaude/docs_reconcile.py:241-252` — `reconcile_snippet_status()` remains the full-sync public write path.
- `teleclaude/docs_reconcile.py:255-267` — `reconcile_snippets_for_purged_slugs()` is the shared purge-time planning entrypoint.
- `teleclaude/services/maintenance_service.py:260-366` — removed-Todo retention cleanup uses the shared planning entrypoint before committing snippet changes and hard-deleting rows.
- `teleclaude/cli/telec/surface.py:388-397` — `telec sync` CLI surface entry.

### Cross-context references

- **workflow** — supplies the roadmap status map used in phase 1b for
  `delivered_by` reconciliation.
- **config** — supplies project root and Mother-project resolution
  consumed by the distribute subprocess.
- **agent_runtime** — phase 3's distribute step deploys to the
  agent_runtime boundary (see `agent-runtime-deployment.md`).

## Known caveats

- Sync is idempotent at the byte level: re-running unchanged source
  produces byte-identical output (stable YAML emission, depth-limited
  expansion, idempotent index writes).
- `--validate-only` exits at `sync.py:64-65` BEFORE reconciliation,
  index build, AND symlink repair. The single validation pass under
  `--validate-only` runs with `enforce_delivered_drift=True`, so it
  catches drift the same way the post-reconciliation pass does on full
  sync — but no reconciliation is attempted to clear that drift. Using
  it in pre-commit means tracked symlinks may stay broken until a full
  sync runs.
- `--warn-only` is risky. It forwards through to the distribute
  subprocess, AND it sets `check=not warn_only` (i.e. `check=False`) on
  the `subprocess.run()` call — so a distribute crash is suppressed and
  `sync()` returns success. Operators relying on a non-zero exit to
  detect distribute failures will not see them under `--warn-only`.
- The distribute step is optional in the sense that a missing
  `scripts/distribute.py` silently skips phase 3 — useful for
  stripped-down deployments, dangerous on a corrupted checkout.
- The roadmap status map is loaded once per sync. Slugs delivered
  during the sync run do not reflect until the next sync.
- The reconcile engine has two v1 callers with different ownership: full sync
  writes delivered-drift corrections during `telec sync`, while routine
  maintenance writes and commits purge-time `delivered_by` removals before
  deleting expired removed rows. `telec sync --validate-only` does neither.
- v1 CLI namespace is `telec sync`. v2 target is `telec context sync`.
  Shedding candidate flagged for migration cleanup.
