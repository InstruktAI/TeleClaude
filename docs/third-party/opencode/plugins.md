---
description: OpenCode plugin and event system (the only hook surface)
id: third-party/opencode/plugins
scope: project
type: third-party
---

# OpenCode Plugins & Events

## Overview

OpenCode exposes lifecycle behavior through in-process **plugins**: async JavaScript/TypeScript
functions loaded into the OpenCode runtime (Bun) that register handlers for named events.
There is no subprocess hook model — no event-name positional argument, no stdin payload, no
external process per event. An event handler can run a command via the Bun `$` API or call
out over HTTP.

## Plugin loading

Plugins load from, in order:

1. Global config (`~/.config/opencode/opencode.json`) — `plugin` array (npm packages)
2. Project config (`opencode.json`) — `plugin` array (npm packages)
3. Global plugin directory: `~/.config/opencode/plugins/`
4. Project plugin directory: `.opencode/plugins/`

`.js` and `.ts` files in the plugin directories load automatically at startup. npm packages
listed in the `plugin` array install automatically via Bun into
`~/.cache/opencode/node_modules/`. Duplicate npm packages load once.

npm registration in `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-helicone-session", "@my-org/custom-plugin"]
}
```

Plugin dependencies can be declared in a `package.json` placed in the config directory;
OpenCode runs `bun install` at startup so plugins can `import` them.

## Plugin function signature

Every plugin exports an async function receiving a context object and returning a map of
event handlers:

```javascript
export const MyPlugin = async ({ project, client, $, directory, worktree }) => {
  return {
    // event handlers go here
  }
}
```

Context parameters:

- `project` — current project information
- `client` — OpenCode SDK client for AI interaction
- `$` — Bun shell API for command execution (the bridge to external processes)
- `directory` — current working directory
- `worktree` — git worktree path

TypeScript variant uses the `Plugin` type from `@opencode-ai/plugin`:

```typescript
import { type Plugin, tool } from "@opencode-ai/plugin"

export const CustomToolsPlugin: Plugin = async (ctx) => {
  return { /* handlers */ }
}
```

## Event handler signature

Handlers are keyed by event name and receive `(input, output)`:

```javascript
"tool.execute.before": async (input, output) => {
  if (input.tool === "bash") {
    output.args.command = escape(output.args.command)
  }
}
```

- `input` carries event-specific read fields (e.g. `input.tool`, `input.cwd`).
- `output` carries mutable fields the handler may modify in place (e.g. `output.args`,
  `output.env`, `output.context`) to influence OpenCode's next action.
- Throwing inside a handler blocks the action (see the `.env` protection example below).

## Full event list

**Command:** `command.executed`

**Files:** `file.edited`, `file.watcher.updated`

**Installation:** `installation.updated`

**LSP:** `lsp.client.diagnostics`, `lsp.updated`

**Messages:** `message.part.removed`, `message.part.updated`, `message.removed`,
`message.updated`

**Permissions:** `permission.asked`, `permission.replied`

**Server:** `server.connected`

**Sessions:** `session.created`, `session.compacted`, `session.deleted`, `session.diff`,
`session.error`, `session.idle`, `session.status`, `session.updated`

**Todo:** `todo.updated`

**Shell:** `shell.env`

**Tools:** `tool.execute.before`, `tool.execute.after`

**TUI:** `tui.prompt.append`, `tui.command.execute`, `tui.toast.show`

**Experimental:** `experimental.session.compacting`

The per-event `input`/`output` field shapes are defined by the `@opencode-ai/plugin` types
and the OpenCode SDK.

## Code examples

Environment injection (`shell.env`):

```javascript
export const InjectEnvPlugin = async () => {
  return {
    "shell.env": async (input, output) => {
      output.env.MY_API_KEY = "secret"
      output.env.PROJECT_ROOT = input.cwd
    },
  }
}
```

Tool gating by throwing (`tool.execute.before`):

```javascript
export const EnvProtection = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool === "read" && output.args.filePath.includes(".env")) {
        throw new Error("Do not read .env files")
      }
    },
  }
}
```

Custom tool registration:

```typescript
import { type Plugin, tool } from "@opencode-ai/plugin"

export const CustomToolsPlugin: Plugin = async (ctx) => {
  return {
    tool: {
      mytool: tool({
        description: "This is a custom tool",
        args: { foo: tool.schema.string() },
        async execute(args, context) {
          return `Hello ${args.foo} from ${context.directory}`
        },
      }),
    },
  }
}
```

Compaction context injection (`experimental.session.compacting`):

```typescript
export const CompactionPlugin: Plugin = async (ctx) => {
  return {
    "experimental.session.compacting": async (input, output) => {
      output.context.push("## Custom Context\n...")
    },
  }
}
```

## Sources

- https://opencode.ai/docs/plugins/
- https://opencode.ai/docs/plugins/#events
- https://opencode.ai/docs/config/
