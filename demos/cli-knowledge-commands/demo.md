# Demo: cli-knowledge-commands

## Validation

```bash
# History search works
telec history search --agent claude "config"
```

```bash
# History show works (requires at least one session to exist)
SESSION_ID=$(telec history search --agent claude "test" 2>/dev/null | sed -n '3p' | awk '{print $NF}')
[ -n "$SESSION_ID" ] && telec history show "$SESSION_ID" --tail 500 | head -10
```

```bash
# Memories save + search + delete round-trip
SAVE_OUT=$(telec memories save "Demo test observation" --title "Demo" --type discovery --project teleclaude)
echo "$SAVE_OUT"
OBS_ID=$(echo "$SAVE_OUT" | grep -oE '[0-9]+')
telec memories search "Demo test" --project teleclaude
telec memories delete "$OBS_ID"
```

```bash
# Help output shows new commands
telec history -h
telec memories -h
```

```bash
# Tool specs retired
test ! -f docs/global/general/spec/tools/agent-restart.md
test ! -f docs/global/general/spec/tools/history-search.md
test ! -f docs/global/general/spec/tools/memory-management-api.md
! grep -q "spec/tools/agent-restart\|spec/tools/history-search\|spec/tools/memory-management" docs/global/baseline.md
```

## Guided Presentation

### Step 1: History search

Run `telec history search --agent claude "config"`. You should see a table of matching
sessions from Claude's transcript history. This replaces the standalone `history.py` script.

### Step 2: History show

Pick a session ID from the search results and run `telec history show <id> --tail 500`.
You should see the tail of the session transcript. Same output as `history.py --show`.

### Step 3: Memory save

Run `telec memories save "Demo observation" --title "Demo" --type discovery --project teleclaude`.
You should see confirmation with the saved observation ID. This replaces raw `curl` to the memory API.

### Step 4: Memory search

Run `telec memories search "Demo" --project teleclaude`. You should see the observation
saved in Step 3 among the results.

### Step 5: Memory timeline

Run `telec memories timeline <id> --before 2 --after 2` using the ID from Step 3.
You should see surrounding observations with timestamps.

### Step 6: Memory delete

Run `telec memories delete <id>` using the same ID. Confirm deletion.

### Step 7: Help output

Run `telec -h` and verify `history` and `memories` appear in the command list.
Run `telec history -h` and `telec memories -h` for subcommand help.

### Step 8: Tool spec retirement

Verify the three standalone tool spec files no longer exist and `docs/global/baseline.md`
no longer references them. Run `telec sync` and confirm clean build.
