---
id: 'general/spec/tools/history-search'
type: 'spec'
scope: 'global'
description: 'Canonical usage of history.py for recovering prior conversations with progressive narrowing.'
---

# History Search Tool — Spec

## What it is

Defines the canonical command signatures and usage patterns for searching native transcript history across agents using `history.py`.

## Canonical fields

- Tool: `$HOME/.teleclaude/scripts/history.py`

### Search mode

- Signature: `history.py --agent <agents> <search terms...>`
- Required input:
  - `--agent`: Comma-separated list of agents (e.g., `claude,gemini`) or `all`.
  - At least one search term.
- Output shape:
  - Matching sessions with date/time, agent, project, topic snippet, session ID, and resume hints.
- Canonical examples:

```bash
$HOME/.teleclaude/scripts/history.py --agent claude memory observations claude-mem
```

```bash
$HOME/.teleclaude/scripts/history.py --agent all api memory save
```

```bash
$HOME/.teleclaude/scripts/history.py --agent claude,gemini checkpoint
```

### Show mode

- Signature: `history.py --agent <agents> --show <session-id> [--tail <chars>]`
- Required input:
  - `--agent`: Agent(s) to search for the transcript (or `all`).
  - `--show`: Session ID or prefix from a search result.
- Optional input:
  - `--tail`: Limit output to last N characters (default 0 = unlimited).
- Output shape:
  - Conversation-only markdown (user + assistant text). Tool calls and tool results are stripped — only what was said and decided.
- Session ID matching: prefix match against extracted IDs and raw filenames, partial UUID match.
- Canonical examples:

```bash
$HOME/.teleclaude/scripts/history.py --agent claude --show f3625680
```

```bash
$HOME/.teleclaude/scripts/history.py --agent all --show c2f69b2b --tail 2000
```

### Workflow: search then show

1. Search to find the session ID: `history.py --agent all <terms>`
2. Show the full transcript: `history.py --agent claude --show <session-id>`
3. Optionally limit output: `--tail 5000` for the last 5000 chars.

## Allowed values

- `--agent`: `claude`, `codex`, `gemini`, comma-separated combinations, or `all`.
- Search terms are free text and support multi-word narrowing by passing additional terms.
- `--show`: Any session ID prefix (minimum 8 chars recommended for uniqueness).
- `--tail`: Non-negative integer (0 = unlimited).

## Known caveats

- Broad terms return noisy results; refine iteratively with additional terms.
- Topic snippets are truncated by the tool output, so a second-pass contextual extraction may be required.
- A no-result search is normal; switch agent or adjust terms before assuming data is missing.
- `--show` with `--tail 0` on large sessions produces substantial output; use `--tail` to control size when ingesting into agent context.
