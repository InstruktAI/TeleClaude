# companies-onboard — Input

# Plan: `telec companies onboard` Implementation

## Context

Company knowledge (org structure, policies, procedures, architecture) needs to flow into all linked projects automatically. Currently, knowledge lives only at global and project scope. The new company scope sits between them: global in reach but filtered by project membership via `company: <slug>` in `teleclaude.yml`.

The documentation snippets for this feature are already written and validated:

- `docs/global/general/concept/company-knowledge.md`
- `docs/global/general/spec/company-scaffolding.md`
- `docs/global/general/procedure/company-onboarding.md`
- `docs/global/general/design/company-knowledge-layer.md`

This plan covers the full implementation: CLI surface, bootstrap logic, enrichment writer, context selection integration, index building, command artifact, and sync integration.

---

## Phase 1: Foundation — Config Schema + Path Constants

**Goal:** Add `company` field to project config and define company storage paths.

### Files to modify

- **`teleclaude/config/schema.py`** (~line 310, `ProjectConfig` class)
  - Add `company: str | None = None` field
  - Add validator: lowercase kebab-case, no special chars
  - This field is NOT in `reject_disallowed_keys` — it's valid at project level

- **`teleclaude/constants.py`**
  - Add `COMPANIES_ROOT = Path.home() / ".teleclaude" / "companies"`
  - Add `COMPANY_DOCS_SUBDIR = "docs"`
  - Add `COMPANY_INBOX_SUBDIR = "inbox"`
  - Add `COMPANY_META_FILENAME = "meta.yaml"`

### Tests

- Config validation accepts/rejects `company` field values
- Path constants resolve correctly

---

## Phase 2: Company Bootstrap Module

**Goal:** Create `teleclaude/company_setup/` package with bootstrap logic.

### New files

- **`teleclaude/company_setup/__init__.py`** — package init
- **`teleclaude/company_setup/bootstrap.py`** — directory scaffolding
  - `bootstrap_company(name: str) -> Path` — derive slug, create dirs, init meta.yaml
  - `ensure_company_exists(slug: str) -> Path` — validate existing company dir
  - Creates: `~/.teleclaude/companies/{slug}/` with `inbox/`, `docs/`, and taxonomy subdirs under `docs/`
  - Initializes `inbox/` as git repo via `git init`
  - Writes initial `meta.yaml` with company_name, slug, created_at

- **`teleclaude/company_setup/inbox.py`** — inbox processing
  - `scan_inbox(company_dir: Path, meta: dict) -> list[dict]` — detect new/changed files
  - `commit_inbox(company_dir: Path) -> None` — stage and commit inbox state
  - First onboard: all files. Re-onboard: `git diff HEAD` + SHA-256 comparison against meta.yaml `processed_files`
  - Skip files with unchanged SHA

- **`teleclaude/company_setup/meta.py`** — meta.yaml read/write
  - `read_meta(company_dir: Path) -> dict`
  - `write_meta(company_dir: Path, meta: dict) -> None`
  - `update_meta_after_onboard(company_dir: Path, processed: list, snippets: list) -> None`

### Existing patterns to reuse

- `teleclaude/project_setup/enrichment.py:read_metadata()` / `write_metadata()` — YAML read/write pattern
- `teleclaude/project_setup/git_repo.py:ensure_git_repo()` — git init pattern

### Tests

- Bootstrap creates correct directory structure
- Meta.yaml round-trips correctly
- Inbox scanning detects new files, skips unchanged SHA
- Git commit in inbox works
- Re-onboard diff detection works

---

## Phase 3: Company Enrichment Writer

**Goal:** Generalize enrichment patterns for company-scoped snippets.

### Strategy

Extract shared merge/render utilities from `teleclaude/project_setup/enrichment.py` into a shared module, then create a parallel company enrichment writer.

### New files

- **`teleclaude/enrichment_core.py`** — shared utilities extracted from project enrichment
  - `render_frontmatter(meta: dict) -> str`
  - `merge_with_human_edits(existing: str, generated: str, marker: str) -> str`
  - `validate_snippet_frontmatter(meta: dict, required_fields: list) -> list[str]`
  - `HUMAN_MARKER = "<!-- human -->"`
  - These are currently inlined in `teleclaude/project_setup/enrichment.py` — extract without changing behavior

- **`teleclaude/company_setup/enrichment.py`** — company-specific enrichment writer
  - `COMPANY_SNIPPET_ID_RE = re.compile(r"^company/(" + "|".join(TAXONOMY_TYPES) + r")/[a-z][a-z0-9-]*$")`
  - `GENERATED_BY_VALUE = "telec-company-onboard"`
  - `write_snippet(company_dir, snippet_id, frontmatter, body)` — validates ID pattern, resolves path under `company_dir/docs/`, writes file
  - `read_existing_snippets(company_dir)` — scan existing company snippets
  - `merge_snippet(existing, generated)` — delegate to `enrichment_core.merge_with_human_edits()`
  - Required frontmatter: `id`, `type`, `scope` (always "global"), `description`, `generated_by`, `generated_at`, `company`

### Files to modify

- **`teleclaude/project_setup/enrichment.py`**
  - Replace inlined merge/render logic with imports from `enrichment_core.py`
  - No behavior change — pure extraction refactor
  - `_SNIPPET_ID_RE` stays here (project-scoped)
  - `GENERATED_BY_VALUE = "telec-init"` stays here

### Tests

- Shared merge logic preserves `<!-- human -->` sections
- Company snippet ID validation accepts/rejects correctly
- Company enrichment writer places files in correct taxonomy dirs
- Frontmatter validation requires all company-specific fields
- Existing project enrichment tests still pass (regression)

---

## Phase 4: CLI Surface and Handler

**Goal:** Add `telec companies` namespace with `onboard` subcommand.

### Files to modify

- **`teleclaude/cli/telec/surface_types.py`**
  - Add `COMPANIES = "companies"` to `TelecCommand` enum

- **`teleclaude/cli/telec/surface.py`**
  - Add `"companies"` CommandDef with subcommands:
    - `"onboard"`: positional `name` arg (first onboard) or `--slug` (re-onboard), `--project` optional
  - Pattern: follow `"bugs"` CommandDef structure (closest parallel with subcommands)

- **`teleclaude/cli/telec/__init__.py`**
  - Add dispatch entry: `TelecCommand.COMPANIES: lambda: _handle_companies(args)`
  - `_handle_companies` routes to subcommand handlers

### New files

- **`teleclaude/cli/telec/companies.py`** — handler module
  - `handle_onboard(name: str | None, slug: str | None, project: Path | None) -> None`
  - Flow:
    1. Resolve company (bootstrap if new, ensure_exists if re-onboard)
    2. Scan inbox for new/changed files
    3. Commit inbox state
    4. If no new files: print "No new material to process" and exit
    5. Dispatch `/telec-company-analyze` session via `telec sessions run`
    6. Print session ID for user to follow

### Existing patterns to reuse

- `teleclaude/project_setup/init_flow.py:_launch_enrichment()` — subprocess dispatch pattern
- `teleclaude/cli/telec/bugs.py` — CLI handler with subcommands pattern

### Tests

- CLI parses `telec companies onboard "Acme Corp"` correctly
- CLI parses `telec companies onboard --slug acme` for re-onboard
- Handler calls bootstrap/scan/commit/dispatch in correct order
- Dispatch constructs correct `telec sessions run` command

---

## Phase 5: Context Selection Integration

**Goal:** Make company snippets discoverable in linked projects.

### Files to modify

- **`teleclaude/context_selector.py`**
  - `SCOPE_ORDER`: add `"company": 0` (same level as global — filtered by membership, not priority)
  - `_load_selected_snippets()` (~line 490): after loading global + project indexes, also load company index if project config has `company` set
    - Resolve `COMPANIES_ROOT / slug / "docs"` as additional snippet root
    - Load its index.yaml
  - `_output_scope()`: add company path detection — if path starts with companies root, scope is "company"
  - `_include_snippet_factory()`: accept company docs root as additional inclusion path
  - `format_snippet_output()`: handle company scope display

- **`teleclaude/snippet_roots.py`**
  - `iter_snippet_roots()` currently only discovers project-local dirs
  - Company dirs are outside project root — context_selector handles them directly
  - No changes needed here

### Key constraint

Company snippets are filtered by the `company` frontmatter field matching the project's declared company slug. This prevents cross-company leakage in multi-company setups.

### Tests

- Company snippets appear in `telec docs index` when project has matching `company` config
- Company snippets do NOT appear when project has no `company` config
- Company snippets do NOT appear when project has a different `company` slug
- Scope display shows "company" for company-scoped snippets
- Multi-company isolation: two companies, two projects, each sees only its own

---

## Phase 6: Index Building for Company Docs

**Goal:** Include company doc directories in `telec sync` index building.

### Files to modify

- **`teleclaude/docs_index.py`**
  - `build_all_indexes()`: after building global + project indexes, scan `~/.teleclaude/companies/*/docs/` directories
  - For each company dir with docs, call `build_index_payload()` (already generic enough to handle any snippet root)
  - Write `index.yaml` inside each company's `docs/` directory
  - `build_index_payload()` should already work — it takes a snippet root and scans taxonomy directories

### Tests

- Index building discovers company doc directories
- Generated `index.yaml` in company docs is well-formed
- Empty company docs dir produces empty index (no crash)
- Multiple companies each get their own index

---

## Phase 7: Command Artifact — `/telec-company-analyze`

**Goal:** Create the command artifact that the dispatched analysis session executes.

### New files

- **`agents/commands/telec-company-analyze.md`**
  - Pattern: follow `agents/commands/telec-init-analyze.md` structure
  - Required reads: `general/spec/company-scaffolding`, `general/procedure/company-onboarding`
  - Steps:
    1. Read meta.yaml for company context
    2. List and classify input files
    3. Map material to taxonomy types
    4. Generate snippets with correct frontmatter (scope: global, company: slug, generated_by: telec-company-onboard)
    5. Validate via `telec sync --validate-only`
    6. Report what was generated
  - Discipline section: concrete findings only, no generic templates, human edits survive

### Tests

- Artifact passes `telec sync --validate-only`

---

## Phase 8: Sync Integration and Verification

**Goal:** Wire company dirs into `telec sync` validation and ensure end-to-end flow.

### Files to modify

- **`teleclaude/sync.py`** (or equivalent sync entry point)
  - Validation pass: include company docs directories in snippet validation
  - Index pass: trigger company index building (Phase 6)

### End-to-end verification

1. Create test company: `telec companies onboard "Test Corp"`
2. Verify directory structure: `~/.teleclaude/companies/test-corp/{inbox,docs,meta.yaml}`
3. Place test material in inbox
4. Re-run: `telec companies onboard --slug test-corp`
5. Verify analysis session dispatched
6. After session completes: verify snippets in `docs/` with correct frontmatter
7. In a project with `company: test-corp`: verify `telec docs index` shows company snippets
8. In a project without company config: verify company snippets are absent
9. Re-onboard with modified inbox file: verify SHA-based skip for unchanged files
10. Verify `telec sync` validates company snippets without errors

---

## File Summary

### New files (10)

1. `teleclaude/company_setup/__init__.py`
2. `teleclaude/company_setup/bootstrap.py`
3. `teleclaude/company_setup/inbox.py`
4. `teleclaude/company_setup/meta.py`
5. `teleclaude/company_setup/enrichment.py`
6. `teleclaude/enrichment_core.py`
7. `teleclaude/cli/telec/companies.py`
8. `agents/commands/telec-company-analyze.md`
9. `tests/test_company_setup/` (test files per phase)
10. `tests/test_cli/test_companies.py`

### Modified files (8)

1. `teleclaude/config/schema.py` — add `company` field
2. `teleclaude/constants.py` — add company path constants
3. `teleclaude/cli/telec/surface_types.py` — add COMPANIES enum
4. `teleclaude/cli/telec/surface.py` — add companies CommandDef
5. `teleclaude/cli/telec/__init__.py` — add dispatch entry
6. `teleclaude/project_setup/enrichment.py` — extract shared logic
7. `teleclaude/context_selector.py` — company scope integration
8. `teleclaude/docs_index.py` — company index building

### Documentation (already written)

- `docs/global/general/concept/company-knowledge.md`
- `docs/global/general/spec/company-scaffolding.md`
- `docs/global/general/procedure/company-onboarding.md`
- `docs/global/general/design/company-knowledge-layer.md`
