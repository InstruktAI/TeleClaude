# Demo: deployment-versioning

## Validation

```bash
# Version is accessible at runtime
python -c "from teleclaude import __version__; assert __version__; print(f'OK: {__version__}')"
```

```bash
# telec version command works
telec version | grep -q "TeleClaude v"
```

```bash
# pyproject.toml has 1.0.0
grep -q 'version = "1.0.0"' pyproject.toml
```

## Guided Presentation

### Step 1: Runtime version access

Run `python -c "from teleclaude import __version__; print(__version__)"`.
Observe: prints `1.0.0` (or current version). This is the foundation — every
other deployment todo depends on version awareness at runtime.

### Step 2: CLI version command

Run `telec version`. Observe: output like `TeleClaude v1.0.0 (channel: alpha,
commit: ea8cc35)`. Shows version, deployment channel, and current commit hash.
Channel defaults to "alpha" until deployment-channels ships.

### Step 3: Verify CI still passes

Confirm `.github/workflows/lint-test.yaml` runs successfully with the version
bump. No CI changes were needed — the existing pipeline handles this.
