# Demo: integration-orchestrator-rollout

## Validation

```bash
telec todo demo validate integration-orchestrator-rollout
```

```bash
rg -n "integration-orchestrator-rollout|integration-events-model|integrator-shadow-mode|integrator-cutover|integration-blocked-flow|after:|group: integration-orchestrator-rollout" todos/roadmap.yaml
```

```bash
sed -n '1,220p' todos/integration-orchestrator-rollout/state.yaml
```

```bash
for slug in integration-events-model integrator-shadow-mode integrator-cutover integration-blocked-flow; do
  echo "== $slug =="
  ls "todos/$slug"/requirements.md "todos/$slug"/implementation-plan.md "todos/$slug"/demo.md "todos/$slug"/state.yaml
done
```

## Guided Presentation

1. Run `telec todo demo validate integration-orchestrator-rollout` to validate
   the demo document structure.
2. Run the roadmap grep command and confirm the orchestrator rollout and its
   four active child slices are present in dependency order.
3. Open `todos/integration-orchestrator-rollout/state.yaml` and confirm:
   `breakdown.assessed: true`, child list is populated, and draft DOR fields exist.
4. Run the per-child artifact loop and confirm each active child has preparation
   artifacts required for draft/gate processing.
5. Explain that this parent todo is a rollout container: implementation work
   proceeds through child slices, while this item tracks readiness, sequencing,
   and blockers.
