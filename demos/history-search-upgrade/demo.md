# Demo: history-search-upgrade

## Validation

```bash
# 1. Verify migration creates the mirrors table and FTS5 index
sqlite3 ~/.teleclaude/teleclaude.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mirrors%';"
```

```bash
# 2. Verify mirror generation — check that recent sessions have mirrors
sqlite3 ~/.teleclaude/teleclaude.db "SELECT session_id, agent, computer, message_count, substr(title, 1, 60) FROM mirrors ORDER BY timestamp_start DESC LIMIT 10;"
```

```bash
# 3. Search via FTS5 — local search
$HOME/.teleclaude/scripts/history.py --agent all mirror generation
```

```bash
# 4. Search remote computer — live API call (parallel)
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

## Guided Presentation

### Step 1: The problem — brute-force scan (before)

Run the old search to show baseline latency:

```
time $HOME/.teleclaude/scripts/history.py --agent claude memory observations
```

Observe: scans up to 500 JSONL files with 8 threads. Takes seconds. Only searches local transcripts. Shows raw transcript snippets with tool noise.

### Step 2: The upgrade — FTS5 search (after)

Run the same search on the upgraded tool:

```
time $HOME/.teleclaude/scripts/history.py --agent claude memory observations
```

Observe: instant results from FTS5 index. Same output format. No JSONL scanning — results come from the local mirrors table. Shows conversation-only context (no tool call noise).

### Step 3: Real-time mirror currency

Start an agent session. Send a message and wait for the agent response. Immediately search for terms from that conversation:

```
# After the agent turn completes (AGENT_STOP fires):
$HOME/.teleclaude/scripts/history.py --agent claude <terms_from_that_conversation>
```

Observe: the mirror for the in-progress session appears in search results. AGENT_STOP triggered mirror regeneration after the agent turn — near-real-time search currency without waiting for session close or background worker.

### Step 4: Mirror as recall artifact

Show a specific session's conversation mirror:

```
$HOME/.teleclaude/scripts/history.py --agent claude --show <session_id>
```

Observe: clean conversation — user questions and agent responses. No tool calls, no thinking blocks, no system metadata. The mirror captures what was _discussed_, not what the agent _did_.

### Step 5: Cross-computer search — live API

Search a remote computer's session history:

```
$HOME/.teleclaude/scripts/history.py --agent all --computer <remote_name> deployment
```

Observe: the search request is sent to the remote daemon's API. Results come back from the remote machine's mirrors table. Same format as local results. No mirror data was replicated — this is a live query.

Search multiple computers in parallel:

```
$HOME/.teleclaude/scripts/history.py --agent all --computer MozBook MozPro memory observations
```

Observe: parallel requests to both daemons. Results assembled, tagged by computer, sorted by time.

### Step 6: Drill-down to raw transcript

When you need forensic detail (exact error messages, file paths, command outputs):

```
$HOME/.teleclaude/scripts/history.py --agent claude --show <session_id> --raw
```

Observe: full transcript from the source computer. The mirror told you WHAT happened; the raw transcript has the forensic details.

### Step 7: Safety net — background worker

Verify the worker catches sessions that events missed:

```bash
# Check worker reconciliation — mirrors.updated_at should be recent for all sessions with transcripts
sqlite3 ~/.teleclaude/teleclaude.db "SELECT COUNT(*) as total_mirrors FROM mirrors;"
sqlite3 ~/.teleclaude/teleclaude.db "SELECT COUNT(*) as stale FROM mirrors WHERE updated_at < datetime('now', '-10 minutes');"
```

Observe: all sessions with transcripts have mirrors. The worker's first pass (on fresh install) processed everything. Subsequent passes catch stragglers.
