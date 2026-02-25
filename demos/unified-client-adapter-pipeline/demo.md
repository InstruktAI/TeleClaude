# Demo: unified-client-adapter-pipeline (Umbrella Orchestration)

## Validation

```bash
rg -n "slug: unified-client-adapter-pipeline|slug: ucap-|group: unified-client-adapter-pipeline|after:" todos/roadmap.yaml
```

```bash
for s in \
  ucap-canonical-contract \
  ucap-truthful-session-status \
  ucap-web-adapter-alignment \
  ucap-tui-adapter-alignment \
  ucap-ingress-provisioning-harmonization \
  ucap-cutover-parity-validation; do
  test -f "todos/$s/requirements.md" &&
  test -f "todos/$s/implementation-plan.md" &&
  test -f "todos/$s/dor-report.md" &&
  test -f "todos/$s/state.yaml"
done
```

```bash
for s in \
  ucap-canonical-contract \
  ucap-truthful-session-status \
  ucap-web-adapter-alignment \
  ucap-tui-adapter-alignment \
  ucap-ingress-provisioning-harmonization \
  ucap-cutover-parity-validation; do
  echo "== $s ==" &&
  rg -n "last_assessed_at|score:|status:" "todos/$s/state.yaml"
done
```

```bash
if rg -n "teleclaude/" todos/unified-client-adapter-pipeline/implementation-plan.md; then
  echo "Parent contains runtime implementation scope; fix required." && exit 1
fi
```

## Guided Presentation

1. Show `todos/roadmap.yaml` and confirm the parent slug acts as an umbrella with child dependencies.
2. Show child artifact existence and DOR metadata outputs from the validation commands.
3. Show the parent-scope guard command passes (no runtime `teleclaude/*` implementation scope in parent implementation plan).
4. Conclude that UCAP executable build work is scoped to child slugs, not the parent slug.
