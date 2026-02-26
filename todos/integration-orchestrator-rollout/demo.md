# Demo: integration-orchestrator-rollout

## Validation

```bash
telec todo validate integration-orchestrator-rollout
```

```bash
rg -n "integration-events-model|integrator-shadow-mode|integrator-cutover|integration-blocked-flow" todos/integration-orchestrator-rollout/dor-report.md
```

```bash
for s in integration-events-model integrator-shadow-mode integrator-cutover integration-blocked-flow; do
  test -f "todos/$s/dor-report.md"
  rg -n "status: pass|score: 8" "todos/$s/state.yaml"
done
```

## Guided Presentation

1. Show the rollout readiness matrix in `todos/integration-orchestrator-rollout/dor-report.md`.
2. Show each child slice has a `pass` gate verdict and `dor.score: 8`.
3. Walk the dependency order: `integration-events-model -> integrator-shadow-mode -> integrator-cutover -> integration-blocked-flow`.
4. Explain the cutover go/no-go policy and no-go containment path recorded in the parent report.
