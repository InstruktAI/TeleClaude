---
name: stack-docs
description: Research and index official documentation for project dependencies. Use when the user asks to capture docs for a library, framework, or tool in the tech stack. Outputs structured snippets under docs/third-party/.
---

# Tech Stack Docs

## Purpose

Capture authoritative documentation for project dependencies and store concise internal snippets under `docs/third-party/` so they are discoverable via `get_context`.

## Scope

- Targeted documentation for libraries, frameworks, and tools used in the project.
- Output stored under `docs/third-party/{library}/`.
- Prefer official vendor documentation; expand to secondary sources only to fill gaps.
- Apply the Parallel Work principle when multiple independent topics or dependencies can be researched simultaneously.

## Inputs

- A library or tool name (e.g., "Redis Streams", "FastAPI", "Textual").
- Optional: specific pages, topics, or APIs to focus on.
- Optional: `pyproject.toml` or `package.json` to auto-detect dependencies.

## Outputs

- Documentation snippet(s) under `docs/third-party/{library}/` following the snippet authoring schema.
- Each snippet includes a **Sources** section and an explicit **Gaps/Unknowns** note when needed.

## Procedure

1. **Define the brief**
   - Clarify the exact topic(s) to document and what will count as “done.”

2. **Gather authoritative sources**
   - Prefer official docs and primary sources.
   - Use Context7, web search, or targeted scraping when appropriate.
   - If official docs are thin or incomplete, identify trusted secondary sources for gaps.

3. **Extract and synthesize**
   - Capture configuration, API usage, constraints, and pitfalls.
   - Separate verified facts from assumptions; do not publish assumptions as facts.

4. **Write the snippet**
   - Follow the snippet schema and keep content concise and actionable.
   - Include **Sources** and **Gaps/Unknowns**.

5. **Index**
   - Observe the snippet is registered by the watcher in `docs/index.yaml`.

6. **Stop condition**
   - Stop when the brief is satisfied and any remaining gaps are explicitly recorded.

**Bulk workflow (stack scan):**

- Enumerate dependencies from `pyproject.toml` or `package.json`.
- For each key dependency, check if docs already exist under `docs/third-party/`.
- Fill only the missing high-impact dependencies first; skip trivial packages.

## Examples

**Fetch docs for a specific library:**
User asks: "Get me the Redis Streams documentation."

1. Locate the official Redis Streams documentation.
2. Capture the core concepts, consumer group behavior, and common pitfalls.
3. Write `docs/third-party/redis/streams.md` and register it in the index.

**Scan the stack for missing docs:**
User asks: "Check what dependencies we're missing docs for."

1. Enumerate dependencies from `pyproject.toml`.
2. Compare against `docs/third-party/`.
3. Report gaps and offer to fill them in priority order.

**Focused topic within a library:**
User asks: "Get me the FastAPI dependency injection docs."

1. Locate the official FastAPI DI docs.
2. Summarize usage patterns and edge cases.
3. Write `docs/third-party/fastapi/dependency-injection.md`.
