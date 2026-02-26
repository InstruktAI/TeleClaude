---
name: tech-stack-docs
description: Research and index official documentation for project dependencies. Use when the user asks to capture docs for a library, framework, or tool in the tech stack. Default output is global (~/.teleclaude/docs/third-party/), unless the user explicitly requests project-only.
---

# Tech Stack Docs

## Required reads

- @~/.teleclaude/docs/software-development/procedure/research/tech-stack-documentation.md

## Purpose

Capture authoritative documentation for project dependencies and store concise internal snippets. Default to global storage under `~/.teleclaude/docs/third-party/` unless the user explicitly requests project-only storage.

## Scope

- Targeted documentation for libraries, frameworks, and tools used in the project.
- **Default output**: `~/.teleclaude/docs/third-party/<library>/` (shared across projects).
- **Project-only output (if requested)**: `docs/third-party/<library>/` within the current repo.
- Check the relevant `index.md` before researching.
- Prefer official vendor documentation; expand to secondary sources only to fill gaps.
- Apply the Parallel Work principle when multiple independent topics can be researched simultaneously.

## Inputs

- A library or tool name (e.g., "Redis Streams", "FastAPI", "Textual").
- Optional: specific pages, topics, or APIs to focus on.
- Optional: `pyproject.toml` or `package.json` to auto-detect dependencies.

## Outputs

- Documentation snippet(s) under the selected scope with Sources and Gaps/Unknowns sections.

## Procedure

Follow the tech stack documentation procedure. Full steps and bulk workflow are in the required reads above.

## Examples

**Fetch docs for a specific library:**
User asks: "Get me the Redis Streams documentation."

1. Locate the official Redis Streams documentation.
2. Capture the core concepts, consumer group behavior, and common pitfalls.
3. Write `~/.teleclaude/docs/third-party/redis/streams.md` (global default).

**Scan the stack for missing docs:**
User asks: "Check what dependencies we're missing docs for."

1. Enumerate dependencies from `pyproject.toml`.
2. Compare against `~/.teleclaude/docs/third-party/` (or `docs/third-party/` if project-only).
3. Report gaps and offer to fill them in priority order.

**Focused topic within a library:**
User asks: "Get me the FastAPI dependency injection docs."

1. Locate the official FastAPI DI docs.
2. Summarize usage patterns and edge cases.
3. Write `~/.teleclaude/docs/third-party/fastapi/dependency-injection.md` (global default).

**Project-only example:**
User asks: "Add project-only docs for the internal Redis usage."

1. Use `docs/third-party/redis/`.
2. Write `docs/third-party/redis/streams.md`.
