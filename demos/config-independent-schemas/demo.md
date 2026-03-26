# Demo: config-independent-schemas

## Medium

CLI terminal — all verification is command-line observable.

## What the user observes

The original bug: `telec docs index` crashes with a `ValidationError` when run from
a person workspace (`~/.teleclaude/people/<name>/`) because the person config YAML
contains keys (`creds`, `notifications`) that `ProjectConfig`'s validator rejects.

After the fix: each config level validates independently, the entry-point loader
detects the workspace type, and the docs pipeline receives pre-validated config
instead of loading it internally.

## Validation

```bash
# 1. Crash scenario — must return global snippets, no crash
cd ~/.teleclaude/people/Maurice\ Faber && telec docs index
# Expected: PHASE 1 output with global snippet index. No ValidationError.
```

```bash
# 2. Normal scenario — project workspace works as before
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && telec docs index
# Expected: PHASE 1 output with project + global snippets.
```

```bash
# 3. Config validation — all levels pass
telec config validate
# Expected: global: passed, person:*: passed, environment: (status).
```

```bash
# 4. Pre-commit hooks — tests, lint, typecheck all green
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/config-independent-schemas
git commit --dry-run --allow-empty -m "test hooks"
# Expected: all hooks pass (or use: pytest tests/unit/config/ -x)
```

```bash
# 5. Spec tests — all pass, no xfail markers
pytest tests/unit/config/test_config_independent_schemas.py -v
# Expected: all tests PASSED (not xfail/xpass).
```
