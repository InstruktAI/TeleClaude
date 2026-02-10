# Scripts

## Required reads

- @docs/project/policy/scripts-standalone-execution.md

## Purpose

This directory contains standalone scripts and helpers that are invoked by AI agent skills, cron jobs, and CLI tools. The directory is symlinked into `~/.teleclaude/scripts` at install time (`make init`), so every file here IS the deployed version.

## Public Surface Rule

This folder is a public runtime command surface. Do not add one-shot migrations, temporary debugging scripts, or personal/AI scratch tooling here. If it is not a stable operator-facing command, place it outside `scripts/` (for example `tools/`).

## Portability Requirement

**All scripts in this directory must run standalone from any working directory using `uv run`.** They must never depend on the `teleclaude` Python package being importable at the top level.

### Why

These scripts are executed by AI agents via skills. The calling context is often a different project, a remote machine, or a process where `teleclaude` is not on `sys.path`. The `~/.teleclaude/scripts` symlink means the script runs from the user's home config, not from within the TeleClaude repo.

### Rules

1. **Shebang**: Every Python script must start with `#!/usr/bin/env -S uv run` (or `#!/usr/bin/env -S uv run --quiet` for scripts that should not show uv output).

2. **PEP 723 inline metadata**: Every Python script that uses third-party dependencies must declare them in a `# /// script` block immediately after the shebang. This allows `uv run` to resolve dependencies automatically without a virtualenv or install step.

   ```python
   #!/usr/bin/env -S uv run
   # /// script
   # requires-python = ">=3.11"
   # dependencies = [
   #     "pyyaml",
   # ]
   # ///
   ```

3. **No `teleclaude` package imports at module level**: Scripts must not use `from teleclaude.* import ...` or `import teleclaude.*` at the top of the file. If you need types or utilities from the teleclaude package, inline them directly in the script.
   - Type aliases like `JsonDict`, `JsonValue` — copy them into the script.
   - Constants — hardcode or read from config files.
   - Utility functions — copy the implementation.

4. **Lazy teleclaude imports are acceptable** only inside `try/except` blocks where failure is handled gracefully (e.g., optional cookie refresh that logs a warning and returns False if the package isn't available).

5. **No `sys.path` manipulation**: Never use `sys.path.insert()` or `parents[N]` tricks to locate the teleclaude package. These break when the script runs from `~/.teleclaude/scripts` instead of the repo checkout.

6. **Self-contained**: Each script must contain all the code it needs to run. Importing between scripts in this directory is acceptable since they share the same symlinked location, but importing from `teleclaude.*` is not.

### Exceptions

Scripts that are ONLY invoked by the daemon process itself (not by agents/skills) may import from `teleclaude` because the daemon's Python environment has the package installed. These scripts currently include:

- `cron_runner.py` — spawned by the daemon's cron scheduler
- `distribute.py` — build/deploy tool run from the repo
- `history.py` — transcript search run from the repo
- `verify_resilience.py` — test script run from the repo

Even for these exceptions, adding PEP 723 metadata is encouraged for future portability.

## Directory Structure

```
scripts/
  helpers/           # Portable helper scripts invoked by agent skills
    git_repo_helper.py   # Clone/update git repos (used by git-repo-scraper skill)
    youtube_helper.py    # YouTube search, history, transcripts (used by youtube skill)
  cron_runner.py     # Cron job executor (daemon-only)
  distribute.py      # Artifact transpiler and deployer (repo-only)
  history.py         # Transcript search tool (repo-only)
  *.sh               # Shell utilities (stable runtime utilities only)
```

## Deployment

`make init` creates a symlink: `~/.teleclaude/scripts -> <repo>/scripts/`. This means:

- Changes to files in this directory take effect immediately — no copy or deploy step.
- The source file IS the deployed file. There is no separate "wrapper" or "deployed copy".
- File permissions must be set (executable bit) in the repo.

## Adding a New Helper

1. Create the script in `scripts/helpers/`.
2. Add the shebang and PEP 723 block with all dependencies.
3. Inline any types or utilities needed from `teleclaude`.
4. Make it executable: `chmod +x scripts/helpers/your_script.py`.
5. Verify it runs from a different directory: `cd /tmp && ~/.teleclaude/scripts/helpers/your_script.py --help`.
