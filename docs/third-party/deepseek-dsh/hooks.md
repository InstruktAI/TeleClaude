---
description: dsh-hooks — Claude Code style hooks for DeepSeek Harness
---

# DeepSeek Harness Hooks

## Overview

DeepSeek Harness (`dsh`) has no native hook system. Hook support comes from the
`dsh-hooks` plugin, which runs shell commands at agent and tool lifecycle
events and reads its configuration from `hooks.json` files in a Claude
Code-compatible JSON shape.

The plugin is a separate upstream package from the harness itself and carries
its own version. Facts below are recorded from the installed package
(`dsh-hooks` 0.3.1) and its README.

## Events

- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `UserPromptSubmit`
- `SessionStart`
- `SessionEnd`
- `Stop`
- `SubagentEnd`

There is no batch-level post-tool event: the plugin has no equivalent of Claude
Code's `PostToolBatch`. `PostToolUse` fires per tool call.

`PreToolUse` returning `deny` surfaces as an official tool-failure card, and the
model sees `Error: <reason>`.

Subagents trigger hooks by default. Subagent payloads carry `agent_id`,
`agent_type`, and `delegation_depth`; `subagents: false` disables them. Subagent
hook commands execute in the triggering agent's own sandbox context.

## Configuration

Four layers, later overriding earlier:

1. global `~/.dsh/hooks.json`
2. preset `<preset-dir>/hooks.json`
3. project `<project-root>/.dsh/hooks.json`
4. project-local `.dsh/hooks.local.json`

The file uses the Claude Code settings shape — `matcher[]` plus `hooks[]`, with
`if`, `timeout`, `once`, and `unsandboxed` per entry. Fields the executor does
not implement (`async`, `asyncRewake`, `statusMessage`, and any `shell` other
than `bash`) are rejected at parse time rather than ignored.

Matcher semantics follow Claude Code's `matchesPattern`: `*` matches all, `A|B`
is pipe-delimited exact matching, anything else is a regular expression. The
`if` condition accepts permission-rule syntax such as `Bash(git *)` and
`Read(*.ts)`.

Deduplication aligns with Claude Code 2.1.88 `hookDedupKey`: `command` keys on
`shell+command+if`, `http` on `url+if`, `prompt`/`agent` on `prompt+if`. A given
key executes once across layers, with the last merged layer winning.
`callback`/`function` hooks are not deduplicated.

Project configuration changes reload automatically via `fs.watchFile`; no
restart is required.

## stdin / stdout protocol

Input arrives as a single line of JSON on the command's stdin:

```json
{
  "session_id": "...",
  "cwd": "...",
  "hook_event_name": "PreToolUse",
  "tool_name": "read",
  "tool_input": { "path": "..." },
  "tool_use_id": "...",
  "agent_id": "<subagent only>",
  "agent_type": "<subagent only>",
  "delegation_depth": 0
}
```

Output is a JSON decision on stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow | deny | ask",
    "permissionDecisionReason": "denied by ...",
    "additionalContext": "..."
  }
}
```

The channel is one-directional: a hook writes stdout and exits, and nothing is
returned to it indicating whether the harness consumed the output.

## Claude Code compatibility boundary

Compatibility covers the configuration shape and a protocol able to express
decisions. It does not extend to Claude Code's plugin surface:

- Carried over: configuration structure, stdin JSON input, stdout JSON decision
  output, deduplication-key semantics.
- Not carried over: Claude Code environment variables such as
  `CLAUDE_PROJECT_DIR` and `CLAUDE_PLUGIN_ROOT`. The project root is available
  as the `cwd` field of the input payload, and DSH has no plugin or skill
  directory to point at.
- Not carried over: `${CLAUDE_PLUGIN_ROOT}` string substitution,
  `CLAUDE_PLUGIN_OPTION_*`, and `CLAUDE_ENV_FILE`.

DSH's internal decisions consume the waterfall return value directly. The stdout
JSON is the means by which a command hook expresses its own decision; it is not
parsed as Claude Code output.

## Explicit non-goals

The plugin does not implement an uninstall lifecycle, dangling-line reminders,
session-scoped configuration profiles, `PreCompact`/`PostCompact`, `prompt`- or
`agent`-type hooks, or a settings page. A configuration's lifetime equals the
lifetime of the directory holding it.

## Packaging and delivery

Delivered as a profile bundle. `cordis.patch.yml` inserts the plugin row on
installation, and the package is installed with
`dsh plugin --profile <profile> add dsh-hooks`. Runtime API and log paths use
the `dsh-hooks` name: `~/.dsh/logs/dsh-hooks/dsh-hooks.log`, and recent records
are available at `GET /dsh-hooks/recent`.

With `dsh-hot-installer` present, adding a new version of a package takes effect
immediately without a restart.

## Verification

Runtime paths only. Install into a profile, run a session, and inspect
`~/.dsh/logs/dsh-hooks/dsh-hooks.log` or `GET /dsh-hooks/recent`.

## Gaps

- Whether concurrently running tool calls produce concurrent `PostToolUse`
  firings is not stated upstream and has not been observed here.
- Which events honor `additionalContext` back into the running turn is not
  enumerated upstream beyond the protocol shape above.

## Sources

- https://github.com/InstruktAI/dsh-plugins
- https://github.com/deepseek-ai/deepseek-harness
- https://github.com/KYinCode/dsh-hot-installer
