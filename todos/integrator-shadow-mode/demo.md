# Demo: integrator-shadow-mode

## Validation

```bash
telec todo demo validate integrator-shadow-mode
```

```bash
# Shadow runtime tests + finalize regression guard
pytest \
  tests/unit/test_integration_shadow_runtime.py \
  tests/unit/test_next_machine_hitl.py::test_post_completion_finalize_requires_ready_and_apply \
  -q
```

```bash
# Shadow module must not contain canonical merge/push commands
rg -n "git -C .* merge|git -C .* push origin main" teleclaude/core/integration || true
```

```bash
# Operator evidence: shadow queue/lease/outcome logs
instrukt-ai-logs teleclaude --since 10m --grep "integration_shadow|integration/main|would_integrate|would_block|superseded"
```

## Guided Presentation

1. Enable shadow mode in config and restart daemon (`make restart`), then verify
   daemon health (`make status`).
2. Trigger a normal finalize-ready flow for a sample slug via the existing
   orchestration path; do not perform cutover.
3. Show persisted queue progression and outcomes (queued -> in_progress ->
   would_integrate/would_block/superseded) from the integration shadow tables.
4. Show logs for lease acquisition/renew/release on key `integration/main` and
   per-candidate outcome records.
5. Prove canonical `main` did not change because of shadow runtime decisions.
6. Show that legacy finalize apply behavior remains intact in this phase
   (regression test + unchanged finalize instruction contract).
