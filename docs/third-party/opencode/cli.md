---
description: OpenCode CLI — non-interactive invocation, session resume, and headless
  server
---

# OpenCode CLI

## Non-interactive invocation

`opencode run` executes a prompt without launching the TUI — the entry point for scripted
and harness-driven use:

```bash
opencode run "Explain the use of context in Go"
opencode run [message..]
```

The message is passed as positional arguments.

## Model and agent selection

```bash
opencode run --model anthropic/claude-3-5-sonnet "Your prompt here"
opencode run --agent my-agent-name "Your prompt here"
```

`--model` uses `provider/model` format. List options with `opencode models [provider]`
(`--refresh` to refetch).

## Session continuation and resume

```bash
opencode run --continue                  # continue the most recent session
opencode run --session <sessionID>       # resume a specific session by id
opencode run --session <sessionID> --fork # branch from an existing session
```

`<sessionID>` is the same id used in the on-disk storage layout (see the sessions doc) and
the HTTP API.

## Working directory

```bash
opencode run --dir /path/to/directory "Your prompt"
opencode [project]                       # TUI: project path as positional arg
```

## Headless server attachment

```bash
opencode serve                                   # start headless HTTP server
opencode run --attach http://localhost:4096 "..." # drive a running server, avoids cold boot
```

## Other notable `run` flags

- `--share` — share the session.
- `--file` / `-f` — attach file(s) to the message.
- `--format json|default` — machine-readable output (`json`) vs human (`default`).
- `--title` — custom session title.
- `--thinking` — display thinking blocks.
- `--dangerously-skip-permissions` — auto-approve all undenied permissions.

## Sources

- https://opencode.ai/docs/cli/
- https://opencode.ai/docs/server/
