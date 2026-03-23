# scoped-agent-lint-test — Input

Make lint and make test should be session-aware. When running inside a tmux agent session, read the session identity from $TMPDIR/teleclaude_identity.json, use _collect_session_touched_files (already exists in todo_scaffold.py) to get the list of files this session touched, then scope lint and test to only those files.

For lint: pass the touched file list directly to ruff, pyright, mypy — they all accept file arguments.

For test: use the 1:1 source-to-test companion convention. teleclaude/x/y.py maps to tests/unit/x/test_y.py. Collect touched source files, map each to its test companion, run only those test files.

This convention is already enforced project-wide — every source file has a test companion. The contract is the mapping, no transitive analysis needed.

The session identity file holds session_id and other fields (previously env vars, now file-based). The transcript lookup from _collect_session_touched_files uses the DB to find native_log_file and parses tool calls to extract file paths.

Benefit: agents currently run full-suite lint (16s) and test (16s) even when they touched 3 files. Scoping cuts this dramatically.
