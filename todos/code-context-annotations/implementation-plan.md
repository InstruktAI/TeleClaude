# Code Context Annotations — Implementation Plan

## Approach

Extend the existing doc snippet pipeline with a new source: annotated Python docstrings. The scraper generates standard markdown snippets that the existing index builder and context selector handle without modification (beyond recognizing the new type). The annotation procedure is designed so agents naturally maintain annotations as part of their normal workflow.

## Design: Data Flow

```
Source Code (.py files)
    │
    │  @context: tags in docstrings
    │
    ▼
AST Scraper (teleclaude/code_context.py)
    │
    │  Parses, extracts, generates markdown
    │
    ▼
docs/project/code-ref/*.md  (generated snippets with frontmatter)
    │
    │  telec sync picks them up
    │
    ▼
docs/project/index.yaml  (includes code-ref entries)
    │
    │  get_context reads the index
    │
    ▼
Phase 1: "code-ref/core/session-manager: Manages tmux session lifecycle"
Phase 2: Full snippet content with signature, module, description
```

## Design: Annotation as Prompt

The annotation isn't just metadata for the scraper — it's a responsibility contract that primes any agent reading the code:

```python
class OutputPoller:
    """Captures real-time terminal output from tmux sessions.

    @context: core/output-poller
    @summary: Streams tmux pane content to listeners via polling.

    Polls tmux pane content at configurable intervals and delivers
    captured output to registered listeners. Handles pane lifecycle
    (attach/detach) and content deduplication.

    This module is responsible for output capture ONLY. It does not
    format, deliver, or persist output — those are adapter concerns.
    """
```

When an agent reads this docstring while modifying `OutputPoller`, the boundary statement ("responsible for X ONLY, not Y") steers it away from scope creep. When a different agent discovers it via `get_context`, the same boundary helps it understand where to make changes. The annotation serves both the scraper and the reader.

## Design: Prompting Strategy

The procedure snippet for annotation hygiene must activate the right behavior without feeling like a burden. Key principles:

1. **Position it at the natural completion point.** After a builder finishes a class or module, it has full context. The annotation is a 2-line addition, not a separate task.

2. **Frame annotations as responsibility contracts.** Not "document this code" but "declare what this code is responsible for." This aligns with how agents already think about modules.

3. **Make the boundary statement the most valuable part.** "This module does X. It does NOT do Y." This is the sentence that prevents scope creep and guides future modifications.

4. **Let the scraper do the formatting work.** Agents write natural prose in docstrings. The scraper handles frontmatter, sections, and index integration. Minimal cognitive load.

## Files to Create

| File                                                                     | Purpose                                              |
| ------------------------------------------------------------------------ | ---------------------------------------------------- |
| `teleclaude/code_context.py`                                             | AST-based scraper: parse, extract, generate markdown |
| `docs/project/code-ref/` (directory)                                     | Output location for generated snippets               |
| `docs/global/software-development/procedure/code-context-annotations.md` | Agent procedure: when/how to annotate                |

## Files to Modify

| File                                 | Change                                               |
| ------------------------------------ | ---------------------------------------------------- |
| `teleclaude/constants.py`            | Add `code-ref` to `TAXONOMY_TYPES` and `TYPE_SUFFIX` |
| `scripts/snippet_schema.yaml`        | Add `code-ref` section schema                        |
| `teleclaude/mcp/tool_definitions.py` | Update hardcoded areas description string (line 65)  |
| `teleclaude/sync.py`                 | Call scraper before `build_all_indexes()` (line 58)  |
| `teleclaude.yml`                     | Add `code_context` config section                    |

Note: `teleclaude/docs_index.py` and `teleclaude/context_selector.py` need NO changes — they read frontmatter generically and filter by type from `TAXONOMY_TYPES`.

## Task Sequence

### Task 1: Taxonomy Extension

**Files**: `teleclaude/constants.py`, `scripts/snippet_schema.yaml`, `teleclaude/mcp/tool_definitions.py`

1. Add `"code-ref"` to `TAXONOMY_TYPES` list.
2. Add `"code-ref": "Code Ref"` to `TYPE_SUFFIX` dict.
3. Add `code-ref` to `snippet_schema.yaml`:
   ```yaml
   code-ref:
     allowed:
       - Signature
       - Module
       - Description
     required:
       - Signature
       - Module
       - Description
   ```
4. Update `tool_definitions.py` line 65 — the hardcoded description string must include `code-ref` in the allowed types list. Since the enum itself is `TAXONOMY_TYPES` (line 61), the actual validation already works once constants.py is updated. Only the human-readable description text needs updating.
5. **Verify**: Run `telec sync` — no regressions. Run existing tests.

### Task 2: Scraper Core

**Files**: `teleclaude/code_context.py`

Data structures:

```python
@dataclass
class AnnotatedElement:
    snippet_id: str          # e.g., "core/session-manager"
    summary: str             # One-line summary for index
    description: str         # Full docstring body (tags stripped)
    signature: str           # Code signature (class/def line)
    module_path: str         # Dotted module path
    source_location: str     # "file.py:ClassName" or "file.py:func_name"
```

Functions:

1. `extract_context_tags(docstring: str) -> dict[str, str] | None`
   - Parses `@context:`, `@summary:` from docstring.
   - Returns None if no `@context:` tag found.
   - Strips tags from the description body.

2. `parse_file(source_path: Path, package_root: Path) -> list[AnnotatedElement]`
   - Uses `ast.parse()` to walk module, class, function nodes.
   - For each node with a docstring containing `@context:`, builds an `AnnotatedElement`.
   - Computes module path from file path relative to package root.

3. `generate_snippet_markdown(element: AnnotatedElement) -> str`
   - Produces markdown with frontmatter: id, type=code-ref, scope=project, description, generated=true, source.
   - Renders H1 title, Signature (fenced code), Module (inline code), Description sections.

4. `scrape_project(project_root: Path, sources: list[str], exclude: list[str]) -> ScrapeResult`
   - Walks source directories, respects exclusions.
   - Calls `parse_file` → `generate_snippet_markdown` for each.
   - Writes to `docs/project/code-ref/` with slug-based filenames.
   - Compares before writing (skip unchanged).
   - Removes stale files not produced in this run.
   - Returns `ScrapeResult(created=N, updated=N, removed=N, errors=[])`.

5. **Verify**: Unit tests (Task 7).

### Task 3: Config Support

**Files**: `teleclaude.yml`

1. Add to project config:
   ```yaml
   code_context:
     sources:
       - teleclaude/
     exclude:
       - teleclaude/migrations/
       - tests/
   ```
2. In `scrape_project`, load config from `teleclaude.yml`. Default to scanning project root Python packages if no config.
3. **Verify**: Scraper respects include/exclude paths.

### Task 4: Sync Integration

**Files**: `teleclaude/sync.py`

1. After validation (Phase 1) and before `build_all_indexes()` (Phase 2), call the scraper:
   ```python
   # Phase 1.5: Generate code-ref snippets from annotations
   from teleclaude.code_context import scrape_project
   result = scrape_project(project_root, sources, exclude)
   if result.created or result.updated or result.removed:
       print(f"Code refs: {result.created} created, {result.updated} updated, {result.removed} removed")
   ```
2. **Verify**: `telec sync` generates snippets from annotated code, then builds index including them.

### Task 5: Seed Annotations

Add `@context:` annotations to 3-5 key modules as proof of concept. Choose modules where the responsibility boundary is already clear:

- `teleclaude/context_selector.py` — context selection pipeline
- `teleclaude/docs_index.py` — snippet index generation
- `teleclaude/code_context.py` — the scraper itself (self-referential proof)
- `teleclaude/mcp_server.py` — MCP tool server
- `teleclaude/sync.py` — artifact sync pipeline

Run `telec sync` and verify snippets appear in `get_context(areas=["code-ref"])`.

### Task 6: Agent Procedure Snippet

**Files**: `docs/global/software-development/procedure/code-context-annotations.md`

````markdown
---
id: software-development/procedure/code-context-annotations
type: procedure
scope: global
description: Add and maintain @context annotations in source code docstrings.
---

# Code Context Annotations — Procedure

## Goal

Maintain accurate, granular code documentation by adding `@context` annotations
to docstrings of key modules, classes, and functions. Annotations are extracted
into documentation snippets that agents discover via `teleclaude__get_context`.

## Preconditions

- The module, class, or function is a public API surface or architecturally significant.
- You have full context of the code (you just wrote or modified it).

## Steps

1. After creating or modifying a key module, class, or function, add `@context:` to
   its docstring:

   ```python
   class OutputPoller:
       """Captures real-time terminal output from tmux sessions.

       @context: core/output-poller
       @summary: Streams tmux pane content to listeners via polling.

       Polls tmux pane content at configurable intervals. Handles pane
       lifecycle and content deduplication.

       This module is responsible for output capture ONLY. It does not
       format, deliver, or persist output.
       """
   ```
````

2. Choose a meaningful snippet ID (`@context: <category>/<name>`).
   - Use the module's architectural role, not its filename.
   - Good: `core/output-poller`, `adapters/telegram`, `mcp/context-tools`
   - Bad: `output_polling_py`, `file-23`, `misc`

3. Write a boundary statement: what this code IS responsible for, and
   optionally what it is NOT responsible for. This is the most valuable
   part of the annotation.

4. Run `telec sync` to generate the snippet and update the index.

## Outputs

- Updated docstring with `@context` annotation.
- Generated snippet in `docs/project/code-ref/`.
- Snippet discoverable via `get_context(areas=["code-ref"])`.

## Recovery

- If `telec sync` reports a duplicate ID, choose a different snippet ID.
- If the annotation doesn't appear in `get_context`, check that the source
  directory is included in `teleclaude.yml` `code_context.sources`.

```

### Task 7: Tests

1. **Unit tests** for `teleclaude/code_context.py`:
   - `test_extract_context_tags` — parses @context, @summary; returns None without tags.
   - `test_parse_file_class` — extracts annotated class with signature.
   - `test_parse_file_function` — extracts annotated function.
   - `test_parse_file_module` — extracts module-level docstring.
   - `test_parse_file_no_annotations` — returns empty list.
   - `test_generate_snippet_markdown` — output has correct frontmatter and sections.
   - `test_scrape_project_idempotent` — second run produces no changes.
   - `test_scrape_project_staleness` — removes files for deleted annotations.

2. **Integration test**: end-to-end from annotated source file to `get_context` output containing the code-ref snippet.

## Risks and Assumptions

| Risk | Mitigation |
|------|------------|
| `@context:` conflicts with existing docstring conventions | Prefix is distinctive; no known Sphinx/Google-style conflict |
| Generated snippets pollute git diffs | Dedicated directory; can `.gitignore` if desired |
| AST parsing fails on syntax errors | Scraper logs warnings, skips unparseable files |
| Snippet ID collisions between hand-written and generated | `code-ref/` prefix namespace prevents collisions |
| Performance on large codebases | AST parsing is fast; only annotated files produce output |
| Agents don't adopt the practice | Procedure snippet primes the behavior; seed annotations demonstrate the pattern |

## Assumptions to Validate

- `build_index_payload` handles `code-ref` type without modification (reads frontmatter generically) — confirmed by reading `docs_index.py`.
- `resource_validation.py` schema validator accepts the new type after `snippet_schema.yaml` is updated.
- `sync.py` insertion point between validation and index building is clean (confirmed: line 58).
- `tool_definitions.py` enum comes from `TAXONOMY_TYPES` (confirmed: line 61), so adding to constants auto-updates the JSON schema. Only the description string (line 65) is hardcoded.
```
