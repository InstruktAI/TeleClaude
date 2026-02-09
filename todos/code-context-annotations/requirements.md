# Code Context Annotations — Requirements

## R1: Annotation Syntax

### R1.1: Tag Format

The annotation uses `@context` tags inside Python docstrings:

```python
class SessionManager:
    """Manages terminal session lifecycle.

    @context: core/session-manager
    @summary: Creates, monitors, and cleans up tmux sessions for AI agents.

    Detailed description follows naturally after the tags.
    Key responsibilities include session creation, output polling, and cleanup.
    """
```

- `@context: <snippet-id>` — Required. Assigns the snippet ID (scoped under `code-ref/`).
- `@summary: <text>` — Optional. One-line summary for the index. Falls back to the first docstring line.
- Tags appear on their own lines, after the opening summary line, before the extended description.

### R1.2: Supported Code Elements

Annotations are valid on:

- **Modules** (module-level docstring)
- **Classes** (class docstring)
- **Functions/methods** (function docstring, including `async def`)

### R1.3: Snippet ID Convention

- The `@context:` value becomes the full snippet ID prefixed with `code-ref/`.
- Example: `@context: core/session-manager` → snippet ID `code-ref/core/session-manager`.
- IDs must be unique across the codebase.

## R2: Scraper

### R2.1: AST-Based Extraction

- Uses Python's `ast` module to parse source files.
- Extracts: code signature, docstring, annotation tags, module path.
- Does not execute or import any source code.

### R2.2: Output Format

For each annotated element, generates a markdown file:

````markdown
---
id: 'code-ref/core/session-manager'
type: 'code-ref'
scope: 'project'
description: 'Creates, monitors, and cleans up tmux sessions for AI agents.'
generated: true
source: 'teleclaude/session_manager.py:SessionManager'
---

# Session Manager — Code Ref

## Signature

\```python
class SessionManager:
\```

## Module

`teleclaude.session_manager`

## Description

Manages terminal session lifecycle.

Detailed description follows naturally after the tags.
Key responsibilities include session creation, output polling, and cleanup.
````

### R2.3: Output Location

- Generated snippets go to `docs/project/code-ref/`.
- File naming: `docs/project/code-ref/<snippet-id-slug>.md` (e.g., `core--session-manager.md`).
- The directory is created automatically if it doesn't exist.

### R2.4: Idempotency and Staleness

- The scraper is idempotent: same source → same output (deterministic).
- Before writing, compares content. Skips unchanged files.
- After generation, removes any files in `docs/project/code-ref/` that no longer correspond to a source annotation.
- Staleness is logged so agents and humans can see what was cleaned up.

### R2.5: Source Directories

- Configured via `teleclaude.yml` under a `code_context` key:
  ```yaml
  code_context:
    sources:
      - teleclaude/
    exclude:
      - teleclaude/migrations/
      - tests/
  ```
- Default: scans the project root's Python packages if no config exists.

## R3: Taxonomy Extension

### R3.1: New Type: `code-ref`

- Added to `TAXONOMY_TYPES` in `teleclaude/constants.py`.
- `TYPE_SUFFIX` maps `code-ref` → `"Code Ref"`.
- Schema section requirements for `code-ref`:
  - Required: `Signature`, `Module`, `Description`
  - Allowed: `Signature`, `Module`, `Description`

### R3.2: Schema Validation

- `scripts/snippet_schema.yaml` updated with `code-ref` sections.
- Validation runs during `telec sync` like any other snippet type.

### R3.3: Context Selection

- `code-ref` appears as a filterable type in Phase 1 (`areas=["code-ref"]`).
- No special handling in Phase 2 — standard snippet content retrieval.

## R4: Sync Integration

### R4.1: Pipeline Position

- The scraper runs in `telec sync` **before** `build_all_indexes()`.
- Order: scraper generates/updates markdown → index builder picks them up → `index.yaml` written.

### R4.2: Generated File Marker

- All generated snippets include `generated: true` in frontmatter.
- This distinguishes them from hand-authored snippets.
- Agents and tooling can filter on this marker.

## R5: Agent Procedure

### R5.1: Annotation Hygiene

- A procedure snippet documents when and how to add `@context:` annotations.
- Agents add annotations when creating new public classes, key modules, or important API surfaces.
- Annotations are not required on internal helpers, tests, or trivial code.

### R5.2: Discovery

- Agents can call `get_context(areas=["code-ref"])` to see all annotated code.
- This serves as a codebase navigation tool in addition to documentation.
