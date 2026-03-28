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
   in the "Baseline index" section of AGENTS.md.
4. **Skill-creator gone**: The `agents/skills/skill-creator/` directory no longer
   exists.
5. **Tests pass**: Full test suite passes with no xfail markers remaining on
   activation-trigger spec files.

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
# 3. Baseline exclusion — these 6 should NOT appear in baseline index
for proc in brainstorming debugging peer-discussion memory-management doc-snippet-authoring agent-artifact-authoring; do
  grep -c "procedure/$proc" docs/global/baseline-progressive.md && echo "FAIL: $proc still in baseline" || echo "OK: $proc removed"
done
```

```bash
# 4. Skill-creator deleted
test -d agents/skills/skill-creator && echo "FAIL: still exists" || echo "OK: deleted"
```

```bash
# 5. Tests pass (targeted)
python -m pytest tests/unit/resource_validation/test_unified_severity_spec.py tests/unit/resource_validation/test_activation_trigger_validation_spec.py tests/unit/test_activation_trigger_distribution_spec.py tests/unit/test_activation_trigger_content_spec.py -v
```

```bash
# 6. No xfail markers remain on spec files
grep -r "pytest.mark.xfail" tests/unit/resource_validation/test_unified_severity_spec.py tests/unit/resource_validation/test_activation_trigger_validation_spec.py tests/unit/test_activation_trigger_distribution_spec.py tests/unit/test_activation_trigger_content_spec.py && echo "FAIL: xfail markers remain" || echo "OK: all xfail removed"
```
