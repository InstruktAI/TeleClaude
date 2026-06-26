---
description: Claude Code local research log for TeleClaude dispatch decisions.
---

# Claude Code Research Log

## Claude Code CLI Usage Snapshot Retrieval

_Recorded: 2026-06-26T14:46:44+02:00. Source classification: own local CLI research; no authoritative public vendor documentation is known in the repository's third-party docs._

Claude Code quota collection uses an observed print-mode slash command path. TeleClaude treats the behavior as local empirical research, not as a publicly documented vendor contract.

### Findings

- `claude -p '/usage'` executes the `/usage` slash command in print mode instead of sending it as a model prompt.
- `--output-format json` wraps the result in a JSON envelope, but the quota details are still embedded in the `result` text field.
- The observed `/usage` path returned `duration_api_ms: 0`, `num_turns: 0`, and zero token usage in the JSON envelope, which indicates the command was handled without a model turn.
- The result text included current session usage, weekly all-model usage, weekly Sonnet-only usage, and reset timestamps.
- The collector should parse the quota text defensively and report an unknown state when the expected usage/reset lines are absent.

### Tested invocation

```bash
claude -p '/usage' \
  --output-format json \
  --no-session-persistence \
  --no-chrome \
  --strict-mcp-config \
  --tools '' \
  --setting-sources user \
  --settings '{"forceLoginMethod":"claudeai","enabledMcpjsonServers":[],"disableAllHooks":true}'
```

### Recommended collector shape

Run the tested print-mode invocation, read the JSON envelope, and extract quota facts from `result`. Store normalized values as remaining fractions for the five-hour and weekly windows under `~/.teleclaude/state/`.

### Caveats

- The useful quota data is formatted text, not a stable JSON schema.
- Subscription wording can change, so absence of a recognizable line should become a reported probe failure rather than a guessed value.
- The command should not expose account identity or raw full output in logs; log only normalized percentages, reset times, and probe status.
