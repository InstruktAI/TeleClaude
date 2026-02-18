# Roadmap

> Work item state lives in `todos/{slug}/state.json`.
> Delivered items: [delivered.md](./delivered.md) | Parked: [icebox.md](./icebox.md)

---

## Help Desk Platform

> Architecture: `docs/project/design/architecture/help-desk-platform.md`
>
> Every person gets a persistent personal agent folder. Members/admins are invited via
> private channels; customers discover the system through public-facing channels.
> Admins additionally observe all sessions via supergroups. Notifications arrive through
> the same bot identity as conversations (credential unity).

- discord-session-routing

Fix forum routing (customer threads in help desk forum, admin threads in all-sessions forum), add Discord-specific stale thread cleanup across all forum structures, and gate project-forum mirroring behind a feature flag.

## Web Interface

- web-interface (after: help-desk) — **BROKEN DOWN**

Next.js 15 web application bridged to TeleClaude via Vercel AI SDK v5. Daemon produces AI SDK UIMessage Stream (SSE) from session transcripts and live output. Frontend uses `useChat` with `DefaultChatTransport`. Auth via NextAuth email OTP (6-digit code, Brevo SMTP adopted from ai-chatbot). Session-to-person metadata binding with visibility routing. React components for each UIMessage part type (reasoning, tool-call, text, custom data parts for send_result artifacts and file links).

## MCP to Tool Specs Migration

> Eliminate the MCP server entirely and replace all 25 `teleclaude__*` MCP tools with
> bash-invocable tool specs loaded via the system prompt and progressive disclosure.
> Extend `telec` CLI with tool subcommands as the unified invocation surface.
> Removes ~3,400 lines of MCP infrastructure.

- mcp-migration-tc-cli — Phase 1: Extend `telec` with tool subcommands and daemon JSON-RPC endpoint
- mcp-migration-tool-spec-docs — Phase 2: Write 24 tool spec doc snippets in 6 taxonomy groups
- mcp-migration-context-integration (after: mcp-migration-tc-cli, mcp-migration-tool-spec-docs) — Phase 3: Wire tool specs into context-selection pipeline, update CLAUDE.md baseline
- mcp-migration-agent-config (after: mcp-migration-context-integration) — Phase 4: Remove MCP from agent session configs, validate all agent types
- mcp-migration-delete-mcp (after: mcp-migration-agent-config) — Phase 5: Delete all MCP server code, wrapper, handlers, definitions (~3,400 lines)
- mcp-migration-doc-updates (after: mcp-migration-delete-mcp) — Phase 6: Update architecture and policy docs, rewrite MCP references

## Demo Celebration System

- next-demo

After every finalize, produce a stored demo artifact — a rich five-act presentation of what was built. Users browse and watch demos at their leisure. Includes `/next-demo` command, `demos/` artifact storage, orchestration wiring (between finalize and cleanup), widget rendering, and lifecycle doc updates.

## Rolling Session Titles

- rolling-session-titles

Re-summarize session titles based on the last 3 user inputs instead of only the first. Use a dedicated rolling prompt that captures session direction. Reset the output message on any title change so the telegram title feedback (native client behavior) floats to the top in Telegram.

## Maintenance

- project-aware-bug-routing

- test-suite-ownership-reset

Freeze non-emergency feature changes and reset test ownership to a deterministic one-to-one model (`source file -> owning unit test`) with path-based test gating. Keep functional/integration tests active as the behavior safety net while rewriting brittle unit tests.

Introduce prefix-based bug routing (`bug-*`) with an atomic per-bug loop (fix -> independent review -> retry/needs_human), while keeping bug intake low-friction (no mandatory project-name argument, explicit TeleClaude override available) and enforcing landing safety gates.
