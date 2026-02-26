# Demo: integrator-cutover

## Validation

```bash
telec todo demo validate integrator-cutover
```

```bash
# Finalize flow must no longer own canonical apply writes
rg -n "FINALIZE APPLY|git -C \"\\$MAIN_REPO\" push origin main|git -C \"\\$MAIN_REPO\" merge" teleclaude/core/next_machine/core.py
```

```bash
# Targeted authority-boundary and integrator-cutover regressions
pytest \
  tests/unit/test_next_machine_hitl.py \
  tests/unit/test_next_machine_state_deps.py \
  tests/unit/test_integration_shadow_runtime.py -q
```

```bash
# Operational evidence for integrator-owned canonical apply
instrukt-ai-logs teleclaude --since 10m --grep "integration/main|integration_completed|integration_blocked|cutover"
```

## Guided Presentation

Medium: CLI + daemon logs.

1. Enable integrator cutover mode in config, restart daemon (`make restart`),
   and verify daemon health (`make status`).
2. Run a normal finalize-prepare flow for a candidate slug until
   `FINALIZE_READY` is emitted; show that orchestrator finalize no longer
   performs canonical merge/push directly.
3. Show integrator lease acquisition (`integration/main`) and queue dequeue for
   the candidate in logs/state.
4. Show successful cutover apply path emits `integration_completed` and advances
   canonical `main`.
5. Trigger a conflict/precondition-failure candidate and show
   `integration_blocked` evidence with no partial canonical push.
6. Toggle containment pause mode and verify queued candidates remain durable
   while canonical writes are paused.
