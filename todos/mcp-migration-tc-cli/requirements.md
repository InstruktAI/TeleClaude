# Requirements: mcp-migration-tc-cli

## Goal

Extend the existing `telec` CLI with tool subcommands and add a daemon JSON-RPC
endpoint, together replacing the MCP protocol as the tool invocation mechanism
for AI agents.

## Scope

### In scope

- **CLI normalization**: remove `telec claude`, `telec gemini`, `telec codex`
  aliases (human-only convenience, not used by agents, leak agent names into
  command surface). Verified: no agent artifacts reference these commands.
- Single `/rpc` endpoint on the daemon API server (Unix socket) accepting JSON-RPC
- New `telec` subcommand groups matching the tool taxonomy: `sessions`,
  `workflow`, `infrastructure`, `delivery`, `channels`
- `telec docs` already covers tool spec queries — tool specs are doc snippets
  indexed by `telec sync` and served by `build_context_output()`. No extension needed.
- `caller_session_id` injection from `$TMPDIR/teleclaude_session_id`
- JSON output to stdout, human-readable errors to stderr
- Graceful degradation when daemon is unavailable

### Out of scope

- Tool spec documentation (separate todo)
- Context-selection integration (separate todo)
- MCP removal (later phase)
- New CLI binary (we extend `telec`, not create a new tool)

## Success Criteria

- [ ] `telec claude`, `telec gemini`, `telec codex` removed from CLI
- [ ] `telec sessions list` returns JSON session list
- [ ] `telec sessions create --computer local --project /path --title "Test"` creates session
- [ ] `telec docs` continues to serve tool spec queries (no changes needed)
- [ ] `telec workflow prepare` returns preparation state
- [ ] `telec deploy` triggers deployment
- [ ] `telec --help` shows new subcommand groups alongside existing ones
- [ ] `telec sessions --help` shows session subcommands
- [ ] Daemon down → clear error message, non-zero exit code
- [ ] `caller_session_id` injected on every RPC call
- [ ] Output is valid JSON parseable by agents

## Constraints

- Extends the existing `telec` CLI — no new binary or script
- JSON-RPC method names: `{group}.{action}` (e.g., `sessions.list`, `workflow.prepare`)
- RPC endpoint reuses existing handler logic — no new business logic
- Existing `telec` subcommands (`sync`, `todo`, `init`) must not regress

## Risks

- Socket path mismatch between telec and daemon: use existing constant
- Large response bodies (session data): must stream/buffer correctly
- Subcommand naming collisions with existing telec commands: audit first
