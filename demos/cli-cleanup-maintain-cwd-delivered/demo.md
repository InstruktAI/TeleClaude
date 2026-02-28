# Demo: cli-cleanup-maintain-cwd-delivered

## Validation

```bash
# 1. Maintain command is gone
telec todo maintain 2>&1 | grep -q "Unknown subcommand\|invalid\|not found" && echo "PASS: maintain removed" || echo "FAIL"
```

```bash
# 2. mark-phase defaults --cwd to current directory
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude
telec todo mark-phase cli-cleanup-maintain-cwd-delivered --phase build --status pending 2>&1 && echo "PASS: mark-phase works without --cwd"
```

```bash
# 3. set-deps defaults --cwd to current directory
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude
telec todo set-deps cli-cleanup-maintain-cwd-delivered 2>&1 && echo "PASS: set-deps works without --cwd"
```

```bash
# 4. roadmap list --delivered shows delivered items
telec roadmap list --include-delivered 2>&1 | grep -q "Delivered" && echo "PASS: --include-delivered flag works"
```

```bash
# 5. roadmap list --delivered-only shows only delivered items
telec roadmap list --delivered-only 2>&1 | grep -q "Delivered" && echo "PASS: --delivered-only flag works"
```

## Guided Presentation

### Step 1: Dead code removed — maintain command

Run `telec todo maintain`. Observe that the command no longer exists — the CLI rejects it as unknown.
This eliminates a stub that returned "MAINTENANCE_EMPTY" and touched nine files.

### Step 2: --cwd defaults to cwd

Run `telec todo mark-phase <any-slug> --phase build --status pending` without `--cwd`.
Observe it succeeds by defaulting to the current working directory, matching the behavior
of `telec todo work` and other commands that use `_PROJECT_ROOT_LONG`.

Same for `telec todo set-deps <slug>` — no `--cwd` needed.

### Step 3: Delivered items visible in roadmap

Run `telec roadmap list --delivered`. Observe that delivered items appear in a "Delivered" group
below the active roadmap, showing slug, date, and description.

Run `telec roadmap list --delivered-only`. Observe only delivered items are shown.
The pattern mirrors `--include-icebox` / `--icebox-only` exactly.
