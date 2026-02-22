# Demo: mcp-migration-delete-mcp

## Medium

CLI / terminal — this is infrastructure deletion, verified through absence.

## What the user observes

1. **No MCP files remain:**

   ```bash
   find teleclaude/ -name '*mcp*' -not -path '*/.venv/*' -not -path '*/__pycache__/*'
   # (empty output)
   ls bin/mcp-wrapper.py
   # No such file or directory
   ```

2. **Daemon starts cleanly without MCP:**

   ```bash
   make restart
   make status
   # Shows daemon running, no MCP-related log errors
   instrukt-ai-logs teleclaude --since 30s --grep mcp
   # No MCP startup or socket messages
   ```

3. **No MCP in dependencies:**

   ```bash
   grep -c 'mcp' pyproject.toml
   # 0
   ```

4. **Docs are clean:**

   ```bash
   grep -rl 'MCP server' docs/project/
   # (empty output or only retained external-integration docs)
   ```

5. **Code quality gates pass:**
   ```bash
   make lint   # clean
   make test   # green
   ```

## Validation commands

```bash
# Comprehensive MCP absence check
grep -rl 'mcp' teleclaude/ --include='*.py' | grep -v __pycache__ | grep -v .venv
# Should return empty

# Verify daemon health post-deletion
make restart && sleep 3 && make status

# Verify import cleanliness
python -c "import teleclaude.daemon; print('OK')"
```
