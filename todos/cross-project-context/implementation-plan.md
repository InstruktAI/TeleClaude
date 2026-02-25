# Implementation Plan: cross-project-context

## Overview

Extend `get_context` to serve documentation across all TeleClaude-aware projects using three-phase progressive disclosure with role-based visibility filtering. The approach adds a project manifest (`~/.teleclaude/projects.yaml`) built by `telec sync`, extends `context_selector.py` with new parameters, and adds a `visibility` frontmatter field to snippets. Existing single-project behavior is untouched.

## Phase 1: Schema and Manifest

### Task 1.1: Add `description` to `ProjectConfig`

**File(s):** `teleclaude/config/schema.py`

- [x] Add `description: Optional[str] = None` field to `ProjectConfig`

### Task 1.2: Create manifest writer

**File(s):** `teleclaude/project_manifest.py` (new)

- [x] Define `ProjectManifestEntry` dataclass: `name` (str), `description` (str), `index_path` (str), `project_root` (str)
- [x] `load_manifest(path: Path) -> list[ProjectManifestEntry]`: Read `~/.teleclaude/projects.yaml`, return entries. Skip entries whose `index_path` no longer exists (stale cleanup).
- [x] `register_project(path: Path, project_root: Path, project_name: str, description: str, index_path: Path)`: Read manifest, upsert entry for this project (match by `project_root`), write back. Create file if missing.
- [x] Manifest path constant: `MANIFEST_PATH = Path("~/.teleclaude/projects.yaml")`

### Task 1.3: Wire `telec sync` to register in manifest

**File(s):** `teleclaude/sync.py`

- [x] After building project index, call `register_project()` with project name, description (from `teleclaude.yml`), and the project index path.
- [x] Only register if a `teleclaude.yml` exists (skip bare repos).

### Task 1.4: Delete dead code

**File(s):** `teleclaude/project_registry.py`, `tests/unit/test_project_registry.py`

- [x] Delete `project_registry.py`
- [x] Delete `test_project_registry.py`
- [x] Remove any imports referencing `project_registry` (grep for usage)

---

## Phase 2: Visibility Frontmatter

### Task 2.1: Add `visibility` to snippet schema

**File(s):** `teleclaude/constants.py` (or wherever allowed frontmatter values live)

- [ ] Add `visibility` as an allowed frontmatter field with values: `public`, `internal`
- [ ] Update snippet validation to accept `visibility` (if validated)

### Task 2.2: Add `visibility` to index generation

**File(s):** `teleclaude/docs_index.py`

- [ ] Read `visibility` from snippet frontmatter during `build_index_payload`
- [ ] Include `visibility` field in `SnippetEntry` TypedDict (default: `internal`)
- [ ] Emit `visibility` in generated `index.yaml` entries

### Task 2.3: Batch-add `visibility: public` to intended public snippets

**File(s):** `docs/**/*.md` (selective)

- [ ] Identify which snippets should be public (concepts, high-level designs, public procedures)
- [ ] Add `visibility: 'public'` to their frontmatter
- [ ] Snippets without the field default to `internal` (safe by default)

---

## Phase 3: Context Selector Expansion

### Task 3.1: Enrich `SnippetMeta`

**File(s):** `teleclaude/context_selector.py`

- [ ] Add `source_project: str = ""` field to `SnippetMeta`
- [ ] Add `project_root: Path | None = None` field to `SnippetMeta`
- [ ] Add `visibility: str = "internal"` field to `SnippetMeta`
- [ ] Update `_load_index` to populate these from the index YAML

### Task 3.2: Cross-project ID rewriting

**File(s):** `teleclaude/context_selector.py`

- [ ] In `_load_index`, when loading a non-current-project index, replace the `project/` prefix in snippet IDs with `{source_project.lower()}/`
- [ ] Single-project mode (current project) keeps `project/` prefix unchanged for backward compatibility

### Task 3.3: Phase 0 — project catalog

**File(s):** `teleclaude/context_selector.py`

- [ ] Add `list_projects: bool = False` parameter to `build_context_output`
- [ ] When `list_projects=True`, load manifest, return formatted project catalog (name, description)
- [ ] Skip entries whose index file doesn't exist

### Task 3.4: Phase 1 — multi-project index loading

**File(s):** `teleclaude/context_selector.py`

- [ ] Add `projects: list[str] | None = None` parameter to `build_context_output`
- [ ] When `projects` is set, load manifest, find matching projects by name (case-insensitive)
- [ ] Load each project's `index.yaml` via `_load_index`, apply ID rewriting
- [ ] Merge into the existing snippet list alongside global snippets
- [ ] When `projects` is not set, behavior is identical to today (current project only)

### Task 3.5: Phase 2 — cross-project retrieval

**File(s):** `teleclaude/context_selector.py`

- [ ] When resolving `snippet_ids`, detect cross-project IDs by prefix (not matching `project/`, `general/`, or domain prefixes). Load those projects' indexes from the manifest on demand.
- [ ] Use `SnippetMeta.project_root` for path resolution (already absolute from `_load_index`)
- [ ] Cross-project `_resolve_requires` stays within the same project's snippets (no cross-project dependency chains)

### Task 3.6: Visibility filtering

**File(s):** `teleclaude/context_selector.py`

- [ ] Add `caller_role: str = "admin"` parameter to `build_context_output`
- [ ] When `caller_role` is not `admin`, filter out snippets where `visibility != "public"` from both phase 1 index and phase 2 content
- [ ] Admin callers see all snippets (no filtering)

### Task 3.7: In-memory cache

**File(s):** `teleclaude/context_selector.py`

- [ ] Module-level cache dict: `_index_cache: dict[str, tuple[float, list[SnippetMeta]]]` keyed by index path, value is `(mtime, snippets)`
- [ ] Before loading an index file, check cache: if path exists in cache and mtime matches, return cached. Otherwise load and update cache.

---

## Phase 4: MCP Wiring and Role Resolution

### Task 4.1: Update `get_context` parameters

**File(s):** `teleclaude/mcp/tool_definitions.py`

- [ ] Add `list_projects` boolean parameter (description: "Return the project catalog instead of snippet index")
- [ ] Add `projects` string array parameter (description: "Filter phase 1 to these project names (lowercase). Omit for current project only.")

### Task 4.2: Wire parameters and role resolution through MCP handler

**File(s):** `teleclaude/mcp/handlers.py`

- [ ] Pass `list_projects` and `projects` through to `build_context_output`
- [ ] Update the `project/` prefix detection logic (line ~975) to handle rewritten cross-project IDs
- [ ] Resolve caller role: `caller_session_id` → `db.get_session()` → session's `user_role` field. Default to `admin` if no session found or field absent.
- [ ] Pass resolved role as `caller_role` to `build_context_output`

### Task 4.3: Store `user_role` on session creation

**File(s):** Session creation path (adapters + command handlers)

- [ ] Add `user_role` field to session record (default: `admin`)
- [ ] Telegram adapter: resolve user identity via `IdentityResolver` at session creation, store resolved role
- [ ] TUI / direct sessions: default to `admin`
- [ ] AI-spawned sessions: inherit parent session's role

---

## Phase 5: Validation

### Task 5.1: Tests

- [ ] Test `load_manifest` / `register_project` round-trip
- [ ] Test `build_context_output` with `list_projects=True`
- [ ] Test `build_context_output` with `projects=["someproject"]` loads that project's index
- [ ] Test ID rewriting: `project/policy/foo` becomes `someproject/policy/foo`
- [ ] Test backward compatibility: no `projects` param gives identical results to current behavior
- [ ] Test stale manifest entry (index file deleted) is skipped gracefully
- [ ] Test cache hit (same mtime) and cache miss (changed mtime)
- [ ] Test visibility filtering: non-admin caller sees only `public` snippets
- [ ] Test visibility filtering: admin caller sees all snippets
- [ ] Test default visibility: snippet without `visibility` field treated as `internal`
- [ ] Run `make test` — all existing tests pass

### Task 5.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
