# Demo: config-wizard-governance

## Validation

```bash
# SC-1: DoD has config-surface gate
grep -q "config wizard updated" docs/global/software-development/policy/definition-of-done.md && echo "PASS: DoD config gate present" || echo "FAIL: DoD config gate missing"
```

```bash
# SC-2: DOR Gate 6 requires config enumeration
grep -q "config keys, env vars" docs/global/software-development/policy/definition-of-ready.md && echo "PASS: DOR config enumeration present" || echo "FAIL: DOR config enumeration missing"
```

```bash
# SC-3: Add-adapter procedure has registration steps
grep -q "_ADAPTER_ENV_VARS" docs/project/procedure/add-adapter.md && grep -q "GuidanceRegistry" docs/project/procedure/add-adapter.md && echo "PASS: Adapter procedure expanded" || echo "FAIL: Adapter procedure missing registration steps"
```

```bash
# SC-4: Teleclaude-config spec has maintenance note
grep -q "must be updated whenever" docs/project/spec/teleclaude-config.md && echo "PASS: Config spec maintenance note present" || echo "FAIL: Config spec maintenance note missing"
```

```bash
# SC-5: telec sync passes
telec sync --validate-only 2>&1 | tail -5
```

```bash
# SC-6: Frontmatter intact on all four files
for f in docs/global/software-development/policy/definition-of-done.md docs/global/software-development/policy/definition-of-ready.md docs/project/procedure/add-adapter.md docs/project/spec/teleclaude-config.md; do
  head -1 "$f" | grep -q "^---" && echo "PASS: $f frontmatter intact" || echo "FAIL: $f frontmatter broken"
done
```

## Guided Presentation

1. **Show the gap**: Run `grep "config wizard" docs/global/software-development/policy/definition-of-done.md` on the pre-change version — zero results. This is the blind spot that allowed WhatsApp to ship without wizard integration.

2. **Walk through each doc change**: Open each of the four files and highlight the added text. Explain how each addition closes a specific governance gap identified in the input.

3. **Run validation**: Execute the bash blocks above to demonstrate all six success criteria pass.

4. **Explain the safety net**: With these governance changes, the next adapter or config-bearing feature will be caught by three independent gates (DoD, DOR, and the procedure itself) before it can ship without wizard integration.
