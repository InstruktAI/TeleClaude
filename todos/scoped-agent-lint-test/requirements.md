# Requirements: scoped-agent-lint-test

## Goal

Reduce lint and test execution time for agent sessions by scoping both to only
the files the current session actually touched, instead of running full-suite
checks against the entire codebase.

## Scope

### In scope

- **Session-aware lint scoping**: When `make lint` (via `tools/lint.sh`) runs
  inside a tmux agent session, detect the session identity and scope lint
  tools to only session-touched files.
- **Session-aware test scoping**: When `make test` (via `tools/test.sh`) runs
  inside a tmux agent session, detect the session identity, map touched source
  files to their test companions using the existing 1:1 mapping convention, and
  run only those test files.
- **Graceful fallback**: When not running inside a session (no identity file),
  or when touched-file collection fails, fall back to full-suite behavior
  identically to current behavior.
- **Pre-commit hook alignment**: The pre-commit hooks that invoke lint
  components should benefit from the same scoping when running inside an agent
  session.

### Out of scope

- Changes to the `_collect_session_touched_files` function itself.
- Changes to `session_identity.py`.
- Changes to how the session identity file is written by the daemon.
- Scoping of `make test-e2e` or `make test-agents` — only unit test scoping.
- Scoping of the `telec sync` validation step in lint (it's fast and
  project-global).
- Scoping of markdown validation (agents rarely change markdown; the check is
  fast).
- Scoping of the guardrails check (it's fast and project-global).

## Success Criteria

- [ ] When an agent session has touched 3 Python files, `make lint` runs ruff,
      pyright, mypy, and pylint against only those files (plus their test
      companions where applicable) instead of the full codebase.
- [ ] When an agent session has touched 3 source files under `teleclaude/`,
      `make test` runs pytest against only the 3 corresponding test companion
      files instead of the full `tests/unit` and `tests/integration` directories.
- [ ] When no session identity file exists (non-agent context), `make lint` and
      `make test` behave identically to their current full-suite behavior.
- [ ] When `_collect_session_touched_files` raises (session not found, no
      transcript, etc.), both commands fall back to full-suite behavior with a
      diagnostic message on stderr.
- [ ] The source-to-test mapping uses the same convention as
      `tools/lint/test_mapping.py`: `teleclaude/x/y.py` maps to
      `tests/unit/x/test_y.py`. [inferred]
- [ ] Non-Python touched files (markdown, YAML, shell scripts) are excluded
      from Python lint tool arguments but do not prevent scoping of the Python
      files. [inferred]
- [ ] The scoping logic is reusable — `tools/lint.sh` and `tools/test.sh`
      share the session detection and file collection rather than duplicating it.
      [inferred]

## Constraints

- The existing `_collect_session_touched_files` function in `todo_scaffold.py`
  is the single source of truth for which files a session touched. It must be
  used as-is, not reimplemented. [inferred — the input explicitly references it]
- The session identity contract is `$TMPDIR/teleclaude_identity.json`
  containing at minimum `session_id`. This is read via
  `session_identity.get_session_id()`.
- Ruff, pyright, mypy, and pylint all accept file/path arguments. The scoping
  must use their native argument interfaces, not wrapper hacks.
- `tools/lint.sh` and `tools/test.sh` are shell scripts. Any Python helper
  they invoke must be callable from shell (e.g., as a subprocess or module
  invocation).
- The fallback to full-suite behavior must be silent except for a brief
  diagnostic on stderr when it occurs due to an error (not when it occurs
  because no session exists — that is normal non-agent usage).
- Test scoping maps only `teleclaude/**/*.py` source files to test companions.
  Touched test files themselves are included directly. [inferred]
- Pyright and mypy may need the full project context to resolve types even when
  checking a subset of files. The builder must verify whether file-scoped
  invocation produces equivalent results to full-project invocation for the
  scoped files. If not, the builder should document the limitation and fall
  back to full-project invocation for those tools. [inferred]

## Risks

- **Type checker accuracy with file-scoped invocation**: Pyright and mypy use
  whole-program analysis. Passing individual files may miss cross-module type
  errors or produce false positives. The builder should validate this and
  document findings.
- **Transcript availability timing**: `_collect_session_touched_files` relies
  on the session transcript being written to disk. If lint/test runs before the
  transcript is flushed, the touched-file set may be incomplete. The fallback
  behavior mitigates this — the worst case is running the full suite, which is
  the current behavior.
