# AGENTS.md

## Purpose

This file provides guidance to agents when working with code in this repository.

## Required reads

- @docs/project/baseline.md
- @docs/project/baseline-progressive.md

## External instrumentation

The TUI is instrumented by the dotfiles repository at `~/Sync/dotfiles/terminal/`. Key interactions:

- **Appearance sync:** `appearance.py reload` sends SIGUSR1 to the TUI when OS dark/light mode changes. The TUI handles this by saving state and restarting (same as SIGUSR2). The appearance script also sets tmux `@appearance_mode` and syncs agent CLI themes.
- **Agent restart:** tmux `bind R` triggers agent restart via the daemon API.
- See `~/Sync/dotfiles/terminal/AGENTS.md` for full architecture.

## Database

The database is at `~/.teleclaude/teleclaude.db` (resolved from `config.database.path`). Mirrors are in `~/.teleclaude/mirrors.db` (separate database). Never guess the path — use `config.database.path` for the main DB.

## Worktree-scoped quality checks

When running inside a worktree (`trees/{slug}/`), `make lint` and `make test` automatically scope to session-touched files. This is not optional — agents in worktrees always get scoped runs.

**How it works:**

- Worktree detection: `git rev-parse --git-common-dir` differs from `--git-dir`
- File resolution: `tools/session_scope.py` reads the agent's session identity from `$TMPDIR/teleclaude_identity.json`, pulls the transcript, and extracts which files the session actually touched
- Lint mode: scopes guardrails, ruff, pyright, mypy, pylint to touched Python files
- Test mode: maps touched source files to companion test files (`teleclaude/x/y.py` → `tests/unit/x/test_y.py`)

**Contract:**

- Worktree → scoped, always. Scope failure is an error (`exit 1`), never a fallback to repo-wide.
- Repo root → repo-wide, always. Humans and CI get full coverage.
- Pre-commit hooks are separately scoped to staged files (unchanged).

**What this means for workers:** `make lint` and `make test` will only check files you touched and their test companions. You will not see errors from code other agents changed. If you see a scope resolution error, that's a real problem — do not work around it.

## TUI work

- After any TUI code change, send SIGUSR2 to the running TUI to reload. (SIGUSR1 is reserved for appearance/theme refresh.)
  ```bash
  kill -USR2 "$(tmux list-panes -t tc_tui -F '#{pane_pid}' | head -1)"
  ```
  The TUI runs as the first pane in the `tc_tui` tmux session. Using tmux's pane PID is reliable regardless of how the process was launched.
- Do not restart the daemon and do not instruct the user to restart telec.
- Verify the change in the TUI after reload.
