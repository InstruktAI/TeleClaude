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
- Signature: `history.py --agent <claude|codex|gemini> <search terms...>`
- Required input:
  - `--agent`
  - At least one search term
- Output shape:
  - Matching sessions with date/time, project, topic snippet, session ID, and resume hint
- Canonical examples:

```bash
$HOME/.teleclaude/scripts/history.py --agent claude memory observations claude-mem
```

```bash
$HOME/.teleclaude/scripts/history.py --agent claude "api/memory/save"
```

```bash
$HOME/.teleclaude/scripts/history.py --agent codex checkpoint
```

## Allowed values

- `--agent` must be one of: `claude`, `codex`, `gemini`
- Search terms are free text and support multi-word narrowing by passing additional terms.

## Known caveats

- Broad terms return noisy results; refine iteratively with additional terms.
- Topic snippets are truncated by the tool output, so a second-pass contextual extraction may be required.
- A no-result search is normal; switch agent or adjust terms before assuming data is missing.
