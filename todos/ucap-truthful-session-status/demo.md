# Demo: ucap-truthful-session-status

## Validation

```bash
rg -n "ucap-truthful-session-status|ucap-web-adapter-alignment|ucap-tui-adapter-alignment" todos/roadmap.yaml
```

```bash
for f in input.md requirements.md implementation-plan.md dor-report.md state.yaml demo.md; do
  test -f "todos/ucap-truthful-session-status/$f" && echo "ok: $f"
done
```

```bash
sed -n '1,120p' todos/ucap-truthful-session-status/requirements.md
```

## Guided Presentation

1. Show roadmap dependency order: canonical contract -> truthful status -> Web/TUI alignments.
2. Show requirements status vocabulary and adapter capability mapping expectations.
3. Show implementation phases that place truth derivation in core and rendering in adapters.
