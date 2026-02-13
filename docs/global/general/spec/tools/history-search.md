---
id: 'general/spec/tools/history-search'
type: 'spec'
scope: 'global'
description: 'Canonical usage of history.py for recovering prior conversations with progressive narrowing.'
---

# History Search Tool — Spec

## What it is

Search and retrieve native transcript history across agents. Run `history.py --help` for full options.

## Canonical fields

- Tool: `$HOME/.teleclaude/scripts/history.py`

### Search

```bash
$HOME/.teleclaude/scripts/history.py --agent claude memory observations
$HOME/.teleclaude/scripts/history.py --agent all api memory save
```

### Show transcript

```bash
$HOME/.teleclaude/scripts/history.py --agent claude --show f3625680
$HOME/.teleclaude/scripts/history.py --agent all --show c2f69b2b --tail 2000
```

### Workflow

1. Search: `history.py --agent all <terms>`
2. Show: `history.py --agent claude --show <session-id>`
3. Limit output: add `--tail 5000`
