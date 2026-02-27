---
description: 'Research and index official documentation for project dependencies as reusable internal snippets stored under ~/.teleclaude/docs/third-party/ or docs/third-party/.'
id: 'software-development/procedure/research/tech-stack-documentation'
scope: 'domain'
type: 'procedure'
---

# Tech Stack Documentation — Procedure

## Goal

Capture authoritative documentation for project dependencies and store concise internal snippets. Avoid re-researching what is already documented. Default to global storage so docs are reusable across projects.

## Preconditions

- A library, framework, or tool name is specified.
- At least one authoritative source is available or discoverable.
- Target scope is determined:
  - **Default**: `~/.teleclaude/docs/third-party/<library>/` (global, shared across projects).
  - **Project-only** (explicit user request): `docs/third-party/<library>/` within the current repo.

## Steps

1. **Define the brief**
   - Clarify the exact topic(s) to document and what will count as done.
   - Check whether docs already exist:
     - Global: `~/.teleclaude/docs/third-party/index.md`
     - Project: `docs/third-party/index.md`
   - If docs exist and are current, return them instead of re-researching.

2. **Gather authoritative sources**
   - Prefer official docs and primary vendor references.
   - Use Context7, web search, or targeted scraping to fill gaps.
   - If official docs are thin, identify trusted secondary sources and note them.

3. **Extract and synthesize**
   - Capture configuration, API usage, constraints, and pitfalls.
   - Separate verified facts from assumptions. Do not publish assumptions as facts.

4. **Write the snippet**
   - Follow the snippet schema: frontmatter, required sections, Sources, Gaps/Unknowns.
   - Keep content concise and actionable.
   - Include a **Sources** section with web links or Context7 snippet IDs.
   - If gaps remain, record them explicitly under **Gaps/Unknowns**.

5. **Stop**
   - Stop when the brief is satisfied and remaining gaps are explicitly recorded.
   - Run `telec sync` after writing the snippet.

**Bulk workflow (stack scan):**

- Enumerate dependencies from `pyproject.toml` or `package.json`.
- For each key dependency, check if docs already exist under `~/.teleclaude/docs/third-party/`.
- Fill only the missing high-impact dependencies first; skip trivial packages.
- Apply the parallel work principle: research independent dependencies simultaneously.

## Outputs

- Documentation snippet(s) under the selected scope with Sources and Gaps/Unknowns sections.
- `telec sync` run after any new or updated snippet.

## Recovery

- If no valid sources are found, do not write a snippet. Report the gap and request clarification or additional sources.
- If scope is unclear, default to global storage and state that choice explicitly.
