# Demo: history-search-upgrade

## Validation

```bash
# 1. Verify migration creates the mirrors table and FTS5 index
make status
sqlite3 teleclaude.db ".tables" | grep mirrors
sqlite3 teleclaude.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mirrors%';"
```

```bash
# 2. Verify mirror generation works — check that recent sessions have mirrors
sqlite3 teleclaude.db "SELECT session_id, agent, computer, message_count, substr(title, 1, 60) FROM mirrors ORDER BY timestamp_start DESC LIMIT 10;"
```

```bash
# 3. Search via FTS5 — local search
$HOME/.teleclaude/scripts/history.py --agent all mirror generation
```

```bash
# 4. Search with computer filter — remote search
$HOME/.teleclaude/scripts/history.py --agent claude --computer MozBook deployment webhook
```

```bash
# 5. Show mirror conversation
$HOME/.teleclaude/scripts/history.py --agent claude --show <session_id_from_step_3>
```

```bash
# 6. Show raw transcript drill-down
$HOME/.teleclaude/scripts/history.py --agent claude --show <session_id_from_step_3> --raw
```

```bash
# 7. Verify distribution — check remote mirrors exist locally
sqlite3 teleclaude.db "SELECT DISTINCT computer FROM mirrors;"
```

## Guided Presentation

### Step 1: The problem — brute-force scan (before)

Run the old search to show baseline latency and limited scope:

```
time $HOME/.teleclaude/scripts/history.py --agent claude memory observations
```

Observe: scans up to 500 JSONL files with 8 threads. Takes seconds. Only searches local computer. Shows raw transcript snippets with tool noise.

### Step 2: The upgrade — FTS5 search (after)

Run the same search on the upgraded tool:

```
time $HOME/.teleclaude/scripts/history.py --agent claude memory observations
```

Observe: instant results from FTS5 index. Same output format. No JSONL scanning — results come from the mirrors table. Shows conversation-only context (no tool call noise).

### Step 3: Cross-computer search

Search a remote computer's session history:

```
$HOME/.teleclaude/scripts/history.py --agent all --computer <remote_name> deployment
```

Observe: results come from the remote daemon's mirrors table via API. Same format as local results. The user doesn't need to SSH anywhere.

### Step 4: Mirror as recall artifact

Show a specific session's conversation mirror:

```
$HOME/.teleclaude/scripts/history.py --agent claude --show <session_id>
```

Observe: clean conversation — user questions and agent responses. No tool calls, no thinking blocks, no system metadata. The mirror captures what was _discussed_, not what the agent _did_.

### Step 5: Drill-down to raw transcript

When you need forensic detail (exact error messages, file paths, command outputs):

```
$HOME/.teleclaude/scripts/history.py --agent claude --show <session_id> --raw
```

Observe: full transcript from the source computer. The mirror told you WHAT happened and WHERE to look deeper. The raw transcript has the details.

### Step 6: Verify distribution

Check that mirrors from other computers are available locally:

```
sqlite3 teleclaude.db "SELECT computer, COUNT(*) as sessions, MIN(timestamp_start) as earliest, MAX(timestamp_start) as latest FROM mirrors GROUP BY computer;"
```

Observe: multiple computers listed. Mirrors arrived via Redis Streams without manual sync. Each computer's sessions are searchable from any other computer.
