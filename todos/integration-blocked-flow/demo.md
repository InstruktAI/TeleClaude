# Demo: integration-blocked-flow

## Validation

```bash
telec todo demo validate integration-blocked-flow
```

```bash
# Targeted blocked-flow contract tests
pytest \
  tests/unit/test_integration_blocked_flow.py \
  tests/unit/test_next_machine_state_deps.py \
  tests/unit/test_next_machine_hitl.py -q
```

```bash
# Inspect persisted blocked outcomes (table name finalized in implementation)
sqlite3 teleclaude.db "
SELECT slug, branch, sha, reason, follow_up_slug, status
FROM integration_blocked_outcomes
ORDER BY id DESC
LIMIT 10;
"
```

```bash
# Operational evidence for blocked events + follow-up linkage
instrukt-ai-logs teleclaude --since 15m --grep "integration_blocked|follow_up_slug|resume_cmd"
```

## Guided Presentation

Medium: CLI + logs + todo artifacts.

1. Start from a cutover-enabled integration path and trigger a candidate known
   to produce a merge conflict during integration apply.
2. Show blocked response output including reason, follow-up slug, and exact
   resume command(s).
3. Open the generated follow-up todo and show it includes blocked candidate
   identity (`slug`, `branch`, `sha`) plus unblock context.
4. Query blocked-outcome persistence and show candidate-to-follow-up linkage.
5. Re-trigger the same blocked candidate and prove no duplicate follow-up todo
   is created (idempotent reuse).
6. Resolve follow-up work, retry integration with the advertised resume command,
   and confirm integration can continue from blocked state.
