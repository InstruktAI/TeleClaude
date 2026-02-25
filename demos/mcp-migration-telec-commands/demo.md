# Demo: mcp-migration-telec-commands

## What Was Built

- 8 new REST endpoints on the TeleClaude daemon (sessions run/unsubscribe/result/widget/escalate, todos prepare/work/maintain/mark-phase/set-deps, deploy)
- `teleclaude/api/auth.py` — dual-factor caller identity verification + role enforcement
- `teleclaude/cli/tool_client.py` — sync httpx client with dual-factor identity headers
- `teleclaude/cli/tool_commands.py` — 22 CLI subcommand handlers
- `teleclaude/cli/telec.py` — all new commands wired into CLI surface + dispatch
- Removed legacy aliases: `telec list`, `telec claude`, `telec gemini`, `telec codex`
- Added `telec todo demo validate|run|create` subcommands

## Validation Steps

### 1. Help output — sessions group

```bash
python -m teleclaude.cli.telec sessions --help | head -5
```

### 2. Help output — todo workflow subcommands

```bash
python -m teleclaude.cli.telec todo --help | grep -E "prepare|work|maintain|mark-phase|set-deps"
```

### 3. Demo subcommands in help

```bash
python -m teleclaude.cli.telec todo demo --help | grep -E "validate|run|create"
```

### 4. Legacy aliases removed

```bash
python -m teleclaude.cli.telec list --help 2>&1 | grep -i "unknown\|not found\|error" || echo "exit: $?"
```

### 5. Computers and projects help

```bash
python -m teleclaude.cli.telec computers --help | head -3
python -m teleclaude.cli.telec projects --help | head -3
```

### 6. Unit tests pass

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mcp-migration-telec-commands && python -m pytest tests/unit/test_telec_cli.py -q 2>&1 | tail -5
```
