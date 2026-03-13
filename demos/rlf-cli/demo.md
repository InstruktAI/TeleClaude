# Demo: rlf-cli

## Validation

```bash
# Verify the new telec package structure exists
test -d teleclaude/cli/telec && echo "telec/ package: OK"
test -f teleclaude/cli/telec/__init__.py && echo "__init__.py: OK"
test -f teleclaude/cli/telec/surface.py && echo "surface.py: OK"
test -f teleclaude/cli/telec/auth.py && echo "auth.py: OK"
test -f teleclaude/cli/telec/help.py && echo "help.py: OK"
test -f teleclaude/cli/telec/handlers/todo.py && echo "handlers/todo.py: OK"
test -f teleclaude/cli/telec/handlers/roadmap.py && echo "handlers/roadmap.py: OK"
```

```bash
# Verify the new tool_commands package structure exists
test -d teleclaude/cli/tool_commands && echo "tool_commands/ package: OK"
test -f teleclaude/cli/tool_commands/__init__.py && echo "__init__.py: OK"
test -f teleclaude/cli/tool_commands/sessions.py && echo "sessions.py: OK"
test -f teleclaude/cli/tool_commands/todo.py && echo "todo.py: OK"
test -f teleclaude/cli/tool_commands/infra.py && echo "infra.py: OK"
```

```bash
# Verify old monolith files are gone
test ! -f teleclaude/cli/telec.py && echo "telec.py removed: OK"
test ! -f teleclaude/cli/tool_commands.py && echo "tool_commands.py removed: OK"
```

```bash
# Verify all new modules are under the 800-line ceiling
for f in \
  teleclaude/cli/telec/__init__.py \
  teleclaude/cli/telec/surface.py \
  teleclaude/cli/telec/surface_types.py \
  teleclaude/cli/telec/auth.py \
  teleclaude/cli/telec/help.py \
  teleclaude/cli/telec/handlers/todo.py \
  teleclaude/cli/telec/handlers/roadmap.py \
  teleclaude/cli/telec/handlers/memories.py \
  teleclaude/cli/tool_commands/sessions.py \
  teleclaude/cli/tool_commands/todo.py \
  teleclaude/cli/tool_commands/infra.py; do
  lines=$(wc -l < "$f")
  if [ "$lines" -le 800 ]; then
    echo "$f: $lines lines (OK)"
  else
    echo "$f: $lines lines (OVER LIMIT)" && exit 1
  fi
done
```

```bash
# Verify external import contracts still work (backward-compat re-exports)
.venv/bin/python -c "
from teleclaude.cli.telec import CLI_SURFACE, is_command_allowed, _usage, _maybe_show_help, _handle_revive
from teleclaude.cli.tool_commands import handle_sessions, handle_agents, handle_todo_create, handle_todo_prepare
print('All external imports: OK')
"
```

```bash
# Verify tests still pass after the structural decomposition
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

## Guided Presentation

1. Show that `teleclaude/cli/telec.py` (4401 lines) no longer exists — replaced by `telec/` package
2. Show that `teleclaude/cli/tool_commands.py` (1458 lines) no longer exists — replaced by `tool_commands/` package
3. Show the new file structure with `ls teleclaude/cli/telec/` and `ls teleclaude/cli/telec/handlers/`
4. Demonstrate the backward-compat imports still work
5. Confirm all 139 tests pass
