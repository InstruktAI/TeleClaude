---
description: Verified runtime surface of the Kimi Code CLI (0.37.2) — launch flags, model aliases, workspace trust, composer rendering, hook events, and session persistence layout.
---

# Kimi Code — Runtime Surface

All facts below were established by driving the CLI on macOS at version
0.37.2 — running it in a pane, capturing the rendered TUI, and reading the
artifacts it wrote — not from vendor documentation.

## Distribution and resolution

- Ships as a single self-contained binary at `<kimi-home>/bin/kimi`
  (~179 MB), installed by its own bootstrap rather than a package manager.
- It is **not placed on `PATH`**. Any caller must resolve the absolute path.
- The path is fixed and survives reinstalls, unlike package-manager CLIs
  whose locations move between installs.
- `kimi upgrade` replaces the binary in place, so anything keyed to the
  binary's identity (for example OS permission grants) should be
  re-verified after an upgrade.

## Launch surface

| Flag                                     | Behavior                                                           |
| ---------------------------------------- | ------------------------------------------------------------------ |
| `-p, --prompt <text>`                    | Run one prompt non-interactively and print the response            |
| `--output-format <text\|stream-json>`    | Output format for prompt mode                                      |
| `-m, --model <alias>`                    | Model alias for this invocation; defaults to `default_model`       |
| `-y, --yolo`                             | Auto-approve regular tool calls; the agent may still ask questions |
| `--auto`                                 | Fully autonomous: the agent will not ask questions                 |
| `--plan`                                 | Start in plan mode                                                 |
| `-S, --session [id]`                     | Resume a session; without an id, pick interactively                |
| `-c, --continue`                         | Continue the previous session for the working directory            |
| `--add-dir <dir>`                        | Add an additional workspace directory; repeatable                  |
| `--agent <name>` / `--agent-file <path>` | Select an agent profile for a new session                          |
| `--skills-dir <dir>`                     | Load skills from an explicit directory; repeatable                 |

Subcommands: `export`, `provider`, `acp` (Agent Client Protocol server over
stdio), `web`, `login` (device-code flow), `doctor`, `vis`, `migrate`,
`upgrade`.

`--yolo` and `--auto` differ in a way that matters for unattended use: `--yolo`
still opens a question channel and will wait on it, while `--auto` does not.

## Models and reasoning effort

Model aliases are the table keys in the CLI's own configuration, and that full
key — not its short `model` value — is what `-m` expects.

Reasoning effort is model configuration, not a launch parameter: a model entry
declares `support_efforts` (for example `low`, `high`, `max`) and a
`default_effort`. No CLI flag overrides it, so an invocation selects effort only
by selecting a model.

## Workspace trust

On first launch in an untrusted directory the TUI renders a **trust gate**
before any composer exists: a two-option menu ("Trust this folder" /
"Don't trust"), navigated with arrow keys and confirmed with Enter. The
selection cursor is `❯` (U+276F).

A granted decision is remembered per directory under
`<kimi-home>/workspace-trust/wd_<name>_<hash>`. Removing that entry restores
the gate.

Any automation that detects readiness by watching for a prompt glyph must not
treat `❯` as an idle prompt: in Kimi it marks a menu selection, and the trust
gate is the first thing rendered.

## Composer rendering

The idle composer is an ASCII `>` inside a box-drawn frame:

```
╭──────────────────────────────╮
│ >                            │
╰──────────────────────────────╯
 kimi-k3 thinking: max   …/path
                     context: 0% (0/1M)
```

The frame edge is `│` (U+2502). A status line carrying the model, thinking
effort, working directory, and context usage renders _below_ the closing
border, so anything extracting live input must stop at that border.

Under tmux the TUI prints: `tmux extended-keys is off. Modified Enter keys may
not work. Add \`set -g extended-keys on\` to ~/.tmux.conf`.

## Session persistence

```
<kimi-home>/sessions/wd_<workspace>_<hash>/session_<uuid>/
    state.json
    agents/<agent-name>/wire.jsonl
    logs/kimi-code.log
```

- A session directory is created **on the session's first message**, not at
  launch. Starting and quitting the TUI leaves no session behind.
- Session ids are `session_<uuid>` — prefixed, so the directory name is not
  itself a bare UUID.
- `state.json` holds `id`, `version`, `cwd`, `archived`, `agents`,
  `lastPrompt`, `title`, `titleKind`, `lastTurnReason`, `createdAt`,
  `updatedAt`.
- `<kimi-home>/session_index.jsonl` maps `sessionId` to `sessionDir` and
  `workDir`, one JSON object per line.
- Every agent within one session writes its own `wire.jsonl`. `main` is the
  session's own agent; sibling directories are subagents of that session and
  are not sessions in their own right.

## Transcript format

`wire.jsonl` is uncompressed JSONL and is **event-sourced** rather than a list
of messages. The first line is `{"type": "metadata", "protocol_version": …,
"created_at": …}`. Every subsequent event carries `time` as epoch
milliseconds.

Observed event types include `context.append_message`,
`context.append_loop_event`, `turn.prompt`, `turn.ended`, `llm.request`,
`llm.tools_snapshot`, `usage.record`, `token_counting.measured`,
`prompt.accepted`, `runtime.set_binding`, `profile.bind`,
`permission.set_mode`, and `plugin.session_start`.

Messages arrive inside `context.append_message`:

```json
{
  "type": "context.append_message",
  "message": {
    "role": "user",
    "content": [{ "type": "text", "text": "…" }],
    "toolCalls": [],
    "origin": { "kind": "user" },
    "id": "msg_…"
  },
  "time": 1787172254964
}
```

Two properties matter for anything consuming these logs. `toolCalls` is a
sibling field of `content`, not a content block type. And `origin.kind`
distinguishes genuine user input from harness-injected entries as explicit
metadata, so classifying real turns needs no text heuristics.

Turn boundaries are explicit: `turn.prompt` carries the input and its origin,
`turn.ended` carries `turnId`, `reason`, and `durationMs`.

## Hooks

The binary carries a hooks subsystem with a `hooks` configuration section and
this event vocabulary:

`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`,
`PostToolUseFailure`, `Stop`, `StopFailure`, `SubagentStop`, `PreCompact`,
`Notification`.

This is the Claude Code event vocabulary, including a `Stop` event, so
turn-completion hooks are available. There is also a plugin API with an
installable marketplace.

For the installed 0.37.2 binary, the Claude-shaped hook result envelope is
usable for permission decisions only: `hookSpecificOutput` carries
`permissionDecision` and `permissionDecisionReason`. The binary contains no
`additionalContext` string, so this runtime exposes no verified hook-driven
context-injection channel. The current vendor Hooks guide describes a broader
surface; installed behavior takes precedence for this version.

## Gaps

- The hook payload shape and registration behavior were not exercised end to
  end. The permission-decision envelope and absence of context injection were
  verified from the installed binary, not by a live hook invocation.
- Non-interactive `--output-format stream-json` was not exercised.
- Behavior of `--agent` profiles and the ACP server was not exercised.

## Sources

- https://moonshotai.github.io/kimi-code/
