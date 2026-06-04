---
description: OpenCode configuration schema, file locations, and headless server API
id: third-party/opencode/configuration
scope: project
type: third-party
---

# OpenCode Configuration

## Config file locations and precedence

Config is **merged** (not replaced) across sources, later overriding earlier:

1. Remote config (`.well-known/opencode`)
2. Global config (`~/.config/opencode/opencode.json`)
3. Custom path (`OPENCODE_CONFIG` env var)
4. Project config (`opencode.json` in project root)
5. `.opencode/` directories
6. Inline config (`OPENCODE_CONFIG_CONTENT` env var)
7. Managed config files (system-level)
8. macOS managed preferences (highest priority)

- Global user settings: `~/.config/opencode/opencode.json`. TUI settings: `~/.config/opencode/tui.json`.
- Project settings: `opencode.json` in the project root (safe to commit).
- `OPENCODE_CONFIG_DIR` selects an alternative config directory (with `agents/`, `commands/`,
  `plugins/`, etc.).
- Both JSON and JSONC (comments) are accepted.

## Keys relevant to harness integration

Plugin registration (npm packages; directory plugins load automatically):

```json
{ "plugin": ["opencode-helicone-session", "@my-org/custom-plugin"] }
```

Permissions — control which tools require approval (default: allow all):

```json
{ "permission": { "edit": "ask", "bash": "ask" } }
```

Tool enablement — disable specific tools entirely:

```json
{ "tools": { "write": false, "bash": false } }
```

Model / provider defaults:

```json
{
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5",
  "provider": { "anthropic": { "options": { "timeout": 600000, "setCacheKey": true } } }
}
```

Agents and default agent (also definable as markdown in `agents/`):

```json
{
  "agent": {
    "code-reviewer": {
      "description": "...",
      "model": "anthropic/claude-sonnet-4-5",
      "prompt": "...",
      "tools": { "write": false, "edit": false }
    }
  },
  "default_agent": "build"
}
```

Custom commands (also definable as markdown in `commands/`):

```json
{ "command": { "test": { "template": "Run full test suite...", "description": "...", "agent": "build" } } }
```

Instruction files and globs:

```json
{ "instructions": ["CONTRIBUTING.md", "docs/guidelines.md", ".cursor/rules/*.md"] }
```

Variable substitution: `{env:VAR}` and `{file:path}` are expanded in config values.

Other keys: `server`, `shell`, `attachment`, `share` (`manual|auto|disabled`), `formatter`,
`lsp`, `mcp`, `snapshot`, `autoupdate`, `compaction`, `watcher`, `enabled_providers` /
`disabled_providers`, `experimental`.

## Headless server & API

`opencode serve [--port <n>] [--hostname <h>] [--cors <origin>]` starts an HTTP server
(default `127.0.0.1:4096`). `OPENCODE_SERVER_PASSWORD` enables HTTP basic auth. Running
`opencode` normally starts both a TUI client and a server; the TUI talks to the server.
OpenAPI 3.1 spec is served at `/doc`.

Session/message endpoints:

- `POST /session` — create a session.
- `GET /session/:id` — retrieve session details.
- `DELETE /session/:id` — delete session and data.
- `POST /session/:id/message` — send a message and wait for the response.
- `POST /session/:id/prompt_async` — send a message asynchronously.
- `POST /session/:id/fork` — branch a child session.

Message body shape:

```json
{ "messageID": "optional-id", "model": "model-name", "agent": "agent-name", "parts": [] }
```

Event streaming (the server-side counterpart to plugin events):

- `GET /event` — SSE stream; first event is `server.connected`, followed by bus events.
- `GET /global/event` — SSE stream of global events.

TUI control (used by IDE plugins to prefill/run prompts):

- `GET /tui/control/next`, `POST /tui/control/response`.

## Sources

- https://opencode.ai/docs/config/
- https://opencode.ai/docs/server/
- https://opencode.ai/docs/cli/
