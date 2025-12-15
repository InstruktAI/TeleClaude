# Roadmap

> **Last Updated**: 2025-12-13
> **Status Legend**: `[ ]` = Todo | `[~]` = In Progress | `[x]` = Done

---

## [x] AI Model Usage

We hit model API rate limits frequently, causing delays and failures. To mitigate this, we plan to implement dynamic model selection based on availability and cost.

For now we will follow the following paradigm:

1. human talks to Claude Opus
2. the AI acts as master to AI sessions it spawns, so those can just get the Sonnet model.

This way we already have some spread over models, helping against rate limiting.

So settle for CLaude Code sessions to be started with the `--model` flag, but ONLY when initiated from an AI via `teleclaude__start_session`.

So we need to append the `--model=sonnet` part at the right place in the command line args.

Another thing we have to get right is in restart_claude.py to detect wether its an AI session so its appends it there as well. Maybe we have to keep a special field in the session DB for that: `initiated_by_ai: bool`. Yes, that is imperative.

### [x] add --model flag to AI calls

Implemented via `claude_model` field in sessions table. MCP tool `teleclaude__start_session` accepts optional `model` parameter.

---

## Documentation

### [x] AI-to-AI Protocol Documentation

Create `docs/ai-to-ai-protocol.md` with full specification, message format, example flows.
