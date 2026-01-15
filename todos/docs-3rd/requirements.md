# Requirements: 3rd‑Party Docs Research and Index

## Objective

Create a fast, repeatable way to collect and maintain third‑party documentation in `docs/3rd/` so AIs can rely on a local, curated source instead of ad‑hoc web searches.

## Outcomes

### O1: Research Skill / Command

Provide a reusable skill or command that performs focused research and writes concise markdown into `docs/3rd/`.

### O2: Documentation Index

Maintain a single index file in `docs/3rd/` that lists all vendor docs, their purpose, and last update time.

### O3: Minimal user input

The research workflow runs from a short prompt and does the rest autonomously (collect, summarize, index).

### O4: Usable by Context Assembler

The resulting docs and index are structured so the context assembler can select and inject them later.

## Acceptance Criteria

- [ ] `docs/3rd/` exists with a clear index file.
- [ ] Research workflow creates new vendor docs without manual formatting.
- [ ] Index is updated on every new or refreshed doc.
- [ ] Docs are concise, source‑linked, and usable for follow‑on work.
