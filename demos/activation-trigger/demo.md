# Demo: activation-trigger

## Medium

CLI — all verification through terminal commands.

## What the user observes

1. **Validation works**: `telec sync --validate-only` passes with all 11 procedures
   carrying `activation_trigger` and no validation errors.
2. **AGENTS.md output**: `telec sync` produces AGENTS.md containing an
   "Activatable Procedures" section with 11 sorted entries showing snippet ID
   and trigger text.
3. **Baseline exclusion**: The 6 previously-baseline procedures no longer appear
   in the generated `AGENTS.md` "Baseline index" section.
4. **Skill-creator gone**: The `agents/skills/skill-creator/` directory no longer
   exists.
5. **Tests pass**: The targeted activation-trigger verification suite passes with
   no xfail markers remaining on activation-trigger spec files.

## Validation

```bash
# 1. Validation passes
telec sync --validate-only
```

```bash
# 2. Activatable Procedures section in AGENTS.md
telec sync
grep -A 15 "Activatable Procedures" AGENTS.md | head -20
```

```bash
# 3. Baseline exclusion — these 6 should NOT appear in the generated AGENTS.md baseline index
baseline_block="$(sed -n '/^## Baseline index/,/^## Activatable Procedures/p' AGENTS.md)"
for proc in brainstorming debugging peer-discussion memory-management doc-snippet-authoring agent-artifact-authoring; do
  if printf '%s\n' "$baseline_block" | grep -Fq "procedure/$proc"; then
    echo "FAIL: $proc still in AGENTS.md baseline index"
  else
    echo "OK: $proc excluded from AGENTS.md baseline index"
  fi
done
```

```bash
# 4. Skill-creator deleted
test -d agents/skills/skill-creator && echo "FAIL: still exists" || echo "OK: deleted"
```

```bash
# 5. Activation-trigger verification suite passes
python -m pytest tests/unit/resource_validation/test_unified_severity_spec.py tests/unit/resource_validation/test_activation_trigger_validation_spec.py tests/unit/test_activation_trigger_distribution_spec.py tests/unit/test_activation_trigger_content_spec.py tests/unit/test_distribute.py tests/unit/test_sync.py tests/unit/project_setup/test_sync.py -v
```

```bash
# 6. No xfail markers remain on spec files
grep -r "pytest.mark.xfail" tests/unit/resource_validation/test_unified_severity_spec.py tests/unit/resource_validation/test_activation_trigger_validation_spec.py tests/unit/test_activation_trigger_distribution_spec.py tests/unit/test_activation_trigger_content_spec.py && echo "FAIL: xfail markers remain" || echo "OK: all xfail removed"
```
