# Implementation Plan: companies-onboard

## Overview

Implement the `telec companies onboard` command and company knowledge layer integration.
The approach adds a new company scope tier between global and project docs, using the
same taxonomy, merge rules, and validation as project enrichment. The plan follows
established codebase patterns: config schema for the project link, constants for paths,
CLI handler mirroring the `bugs` command structure, enrichment writer paralleling
`project_setup/enrichment.py`, and context selector extension for the new scope tier.

Shared merge/render logic is extracted from `project_setup/enrichment.py` into
`enrichment_core.py` to avoid cross-package coupling between `project_setup` and
`company_setup`. The extraction is behavior-preserving — existing project enrichment
tests serve as the regression guard.

## Task 1: Config schema — add `company` field to `ProjectConfig`

**File(s):**

- `teleclaude/config/schema.py`
- `teleclaude.sample.yml`

**What:** Add `company: str | None = None` field to `ProjectConfig` (after line 309,
alongside other optional project-level fields). Add a field validator enforcing
lowercase kebab-case format when the value is not None. Update `teleclaude.sample.yml`
to document the `company` field with a commented example showing usage.

**Why:** The `company` field is the project-to-company link. Without it, the context
selector has no signal for which company's docs to load. The validator prevents slug
mismatches caused by case or special characters. The field uses `str | None` rather
than a custom type because the slug is a simple identifier — the same pattern as
`project_name: str | None`. The `teleclaude.sample.yml` update is required by DoD
when new project-level config keys are introduced — it shows users how to declare the
company link for their project.

**Verification:**

- Unit test (xfail → GREEN): `ProjectConfig(company="acme")` accepted.
  (`tests/unit/config/test_project_config_company_field.py::test_project_config_accepts_valid_slug`)
- Unit test (xfail → GREEN): `ProjectConfig(company="Acme Corp")` raises `ValidationError`.
  (`tests/unit/config/test_project_config_company_field.py::test_project_config_rejects_uppercase`)
- Unit test (xfail → GREEN): `ProjectConfig(company=None)` accepted (default).
  (`tests/unit/config/test_project_config_company_field.py::test_project_config_accepts_none`)
- Unit test (xfail → GREEN): `ProjectConfig(company="acme-corp")` accepted (kebab-case).
  (`tests/unit/config/test_project_config_company_field.py::test_project_config_accepts_kebab_case`)
- Unit test (xfail → GREEN): `ProjectConfig(company="")` raises `ValidationError`.
  (`tests/unit/config/test_project_config_company_field.py::test_project_config_rejects_empty_string`)
- Regression: existing `reject_disallowed_keys` still blocks `people`, `ops`, etc.
- `teleclaude.sample.yml` contains a commented `company: <slug>` example under the
  project-level section with a brief usage note.

- [x] Complete this task

## Task 2: Path constants for company storage

**File(s):** `teleclaude/constants.py`

**What:** Add company-related path constants following the existing `DATABASE_DIR` /
`HELP_DESK_SUBDIR` pattern:

- `COMPANIES_ROOT = str(Path("~/.teleclaude/companies").expanduser())`
- `COMPANY_DOCS_SUBDIR = "docs"`
- `COMPANY_INBOX_SUBDIR = "inbox"`
- `COMPANY_META_FILENAME = "meta.yaml"`

**Why:** Centralizing path constants prevents hard-coded paths across modules. The
`expanduser()` pattern matches `DATABASE_DIR`. Subdirectory names as string constants
(not full paths) because they're relative to a company directory resolved at runtime.

**Verification:**

- Unit test (xfail → GREEN): `COMPANIES_ROOT` resolves to `~/.teleclaude/companies` expanded.
  (`tests/unit/config/test_project_config_company_field.py::test_companies_root_constant`)
- Unit test (xfail → GREEN): `COMPANY_META_FILENAME` equals `"meta.yaml"`.
  (`tests/unit/config/test_project_config_company_field.py::test_company_meta_filename_constant`)

- [x] Complete this task

## Task 3: Extract shared enrichment utilities into `enrichment_core.py`

**File(s):**

- `teleclaude/enrichment_core.py` (new)
- `teleclaude/project_setup/enrichment.py` (modify)

**What:** Extract the following from `project_setup/enrichment.py` into a new
`teleclaude/enrichment_core.py` module:

- `HUMAN_MARKER = "<!-- human -->"` (line 47)
- `GENERATED_BY_KEY = "generated_by"` (line 49)
- `merge_snippet(existing_content, generated_content)` (lines 160-174)
- `render_snippet(snippet_id, content, metadata, generated_by)` — generalized from
  `_render_snippet()` (lines 229-243), now accepting `generated_by` as a parameter
  instead of hard-coding `GENERATED_BY_VALUE`.

Update `project_setup/enrichment.py` to import from `enrichment_core` and retain its
module-level `GENERATED_BY_VALUE = "telec-init"` and `_SNIPPET_ID_RE` (project-scoped).
The private `_render_snippet()` becomes a thin wrapper calling `enrichment_core.render_snippet()`
with `generated_by=GENERATED_BY_VALUE`.

**Why:** Both project and company enrichment need the same merge and render logic. Without
extraction, `company_setup` would import from `project_setup` — a cross-package dependency
that conflates project-specific and shared concerns. The `generated_by` parameter makes
the renderer reusable without coupling to a specific constant.

**Verification:**

- Regression: all existing `tests/unit/project_setup/test_enrichment*.py` tests pass unchanged.
- Unit test (xfail → GREEN): `enrichment_core.merge_snippet()` preserves `<!-- human -->` sections.
  (`tests/unit/test_enrichment_core.py::test_merge_snippet_preserves_human_section`)
- Unit test (xfail → GREEN): `enrichment_core.render_snippet()` produces valid frontmatter with the
  supplied `generated_by` value.
  (`tests/unit/test_enrichment_core.py::test_render_snippet_includes_supplied_generated_by`)
- Unit test (xfail → GREEN): `HUMAN_MARKER` and `GENERATED_BY_KEY` importable from `enrichment_core`.
  (`tests/unit/test_enrichment_core.py::test_enrichment_core_exports_constants`)

- [x] Complete this task

## Task 4: Company bootstrap module

**File(s):**

- `teleclaude/company_setup/__init__.py` (new)
- `teleclaude/company_setup/bootstrap.py` (new)
- `teleclaude/company_setup/meta.py` (new)

**What:**

`bootstrap.py`:

- `bootstrap_company(name: str) -> Path` — derive slug via `teleclaude.slug.normalize_slug()`,
  create `~/.teleclaude/companies/{slug}/` with `inbox/`, `docs/`, and taxonomy subdirs
  under `docs/`. Initialize `inbox/` as a git repo. Write initial `meta.yaml`. Return
  company directory path. Fail if slug already exists with a different `company_name` in
  `meta.yaml` (collision guard per design spec).
- `ensure_company_exists(slug: str) -> Path` — validate the company directory exists and
  has a valid `meta.yaml`. Return company directory path. Raise `ValueError` if missing.

`meta.py`:

- `read_meta(company_dir: Path) -> dict` — load `meta.yaml` with YAML safe_load.
- `write_meta(company_dir: Path, meta: dict) -> None` — write `meta.yaml` with YAML safe_dump.
- `update_meta_after_onboard(company_dir: Path, processed: list, snippets: list) -> None` —
  update timestamps, increment `onboard_count`, update `processed_files` and `snippets_generated`.

**Why:** The bootstrap module mirrors `project_setup/` package structure — one package per
setup concern. The slug collision guard prevents two companies mapping to the same directory
(per design spec failure mode). Git init in inbox enables `git diff` for change detection
on re-onboard. The `normalize_slug()` reuse ensures consistent slug derivation project-wide.

**Verification:**

- Unit test (xfail → GREEN): `bootstrap_company("Acme Corp")` creates correct directory tree.
  (`tests/unit/company_setup/test_bootstrap.py::test_bootstrap_company_creates_directory_tree`)
- Unit test (xfail → GREEN): `bootstrap_company()` initializes inbox as git repo.
  (`tests/unit/company_setup/test_bootstrap.py::test_bootstrap_company_inits_inbox_git_repo`)
- Unit test (xfail → GREEN): `bootstrap_company()` writes `meta.yaml` with name, slug, `created_at`.
  (`tests/unit/company_setup/test_bootstrap.py::test_bootstrap_company_writes_meta_yaml`)
- Unit test (xfail → GREEN): `bootstrap_company()` raises on slug collision with different name.
  (`tests/unit/company_setup/test_bootstrap.py::test_bootstrap_company_raises_on_slug_collision`)
- Unit test (xfail → GREEN): `ensure_company_exists()` returns path for valid company, raises for missing.
  (`tests/unit/company_setup/test_bootstrap.py::test_ensure_company_exists_behavior`)
- Unit test (xfail → GREEN): `read_meta()` / `write_meta()` round-trip correctly.
  (`tests/unit/company_setup/test_bootstrap.py::test_meta_roundtrip`)
- Unit test (xfail → GREEN): `update_meta_after_onboard()` increments `onboard_count`.
  (`tests/unit/company_setup/test_bootstrap.py::test_update_meta_after_onboard_increments_count`)

- [x] Complete this task

## Task 5: Company inbox processing

**File(s):** `teleclaude/company_setup/inbox.py` (new)

**What:**

- `scan_inbox(company_dir: Path, meta: dict) -> list[dict]` — detect new/changed files.
  First onboard: all files. Re-onboard: `git diff HEAD` in inbox + SHA-256 comparison
  against `meta["processed_files"]`. Each result dict has `path`, `sha256`, `is_new`.
  Skip files with unchanged SHA.
- `commit_inbox(company_dir: Path) -> None` — stage all files in inbox, commit with a
  timestamp message. Uses `subprocess.run(["git", ...])` following the pattern in
  `project_setup/git_repo.py`.

**Why:** SHA-based skip prevents re-processing unchanged material (even if renamed).
Git commit creates the baseline for next re-onboard diff. Separating inbox from bootstrap
keeps the modules focused: bootstrap creates structure, inbox manages change detection.

**Verification:**

- Unit test (xfail → GREEN): `scan_inbox()` on first onboard returns all files.
  (`tests/unit/company_setup/test_inbox.py::test_scan_inbox_first_onboard_returns_all_files`)
- Unit test (xfail → GREEN): `scan_inbox()` on re-onboard skips unchanged SHA files.
  (`tests/unit/company_setup/test_inbox.py::test_scan_inbox_skips_unchanged_sha`)
- Unit test (xfail → GREEN): `scan_inbox()` detects modified files (different SHA).
  (`tests/unit/company_setup/test_inbox.py::test_scan_inbox_detects_modified_files`)
- Unit test (xfail → GREEN): `commit_inbox()` stages and commits inbox files.
  (`tests/unit/company_setup/test_inbox.py::test_commit_inbox_commits_files`)
- Unit test (xfail → GREEN): empty inbox returns empty list without crash.
  (`tests/unit/company_setup/test_inbox.py::test_scan_inbox_empty_returns_empty_list`)

- [x] Complete this task

## Task 6: Company enrichment writer

**File(s):** `teleclaude/company_setup/enrichment.py` (new)

**What:**

- `COMPANY_SNIPPET_ID_RE = re.compile(r"^company/(" + "|".join(TAXONOMY_TYPES) + r")/[a-z][a-z0-9-]*$")`
- `GENERATED_BY_VALUE = "telec-company-onboard"`
- `validate_snippet_id(snippet_id: str) -> bool` — match against `COMPANY_SNIPPET_ID_RE`.
- `snippet_id_to_path(company_dir: Path, snippet_id: str) -> Path` — resolve under
  `company_dir/docs/`. Pattern: `company/{taxonomy}/{slug}` → `company_dir/docs/{taxonomy}/{slug}.md`.
- `write_snippet(company_dir, snippet_id, content, metadata)` — validate ID, resolve path,
  render via `enrichment_core.render_snippet()` with `generated_by=GENERATED_BY_VALUE`,
  add `company` field to frontmatter.
- `read_existing_snippets(company_dir)` — scan `company_dir/docs/` for snippets with
  `generated_by: telec-company-onboard`.
- `refresh_snippet(company_dir, snippet_id, content, metadata)` — create/update/skip
  following the same pattern as `project_setup/enrichment.refresh_snippet()`.

Required frontmatter fields per spec: `id`, `type`, `scope` (always `"global"`),
`description`, `generated_by`, `generated_at`, `company`.

**Why:** Parallels `project_setup/enrichment.py` with company-specific ID validation
and path resolution. Uses `enrichment_core` for shared merge/render to avoid duplication.
The `company` frontmatter field enables context selector filtering by project membership.

**Verification:**

- Unit test (xfail → GREEN): `validate_snippet_id("company/policy/security")` → True.
  (`tests/unit/company_setup/test_enrichment.py::test_validate_snippet_id_accepts_valid`)
- Unit test (xfail → GREEN): `validate_snippet_id("project/policy/security")` → False.
  (`tests/unit/company_setup/test_enrichment.py::test_validate_snippet_id_rejects_non_company`)
- Unit test (xfail → GREEN): `write_snippet()` writes file with all required frontmatter fields.
  (`tests/unit/company_setup/test_enrichment.py::test_write_snippet_writes_required_frontmatter`)
- Unit test (xfail → GREEN): `write_snippet()` includes `company` field matching company slug.
  (`tests/unit/company_setup/test_enrichment.py::test_write_snippet_includes_company_field`)
- Unit test (xfail → GREEN): `read_existing_snippets()` finds snippets by `generated_by` marker.
  (`tests/unit/company_setup/test_enrichment.py::test_read_existing_snippets_filters_by_generated_by`)
- Unit test (xfail → GREEN): `refresh_snippet()` preserves `<!-- human -->` sections on update.
  (`tests/unit/company_setup/test_enrichment.py::test_refresh_snippet_preserves_human_sections`)
- Unit test (xfail → GREEN): `snippet_id_to_path()` resolves correctly under `company_dir/docs/`.
  (`tests/unit/company_setup/test_enrichment.py::test_snippet_id_to_path_resolves_correctly`)

- [x] Complete this task

## Task 7: CLI surface definition — add `companies` namespace

**File(s):**

- `teleclaude/cli/telec/surface_types.py`
- `teleclaude/cli/telec/surface.py`

**What:**

In `surface_types.py`: add `COMPANIES = "companies"` to `TelecCommand` enum (alphabetical order,
after `CHANNELS`).

In `surface.py`: add `"companies"` `CommandDef` to `CLI_SURFACE` dict with subcommand:

- `"onboard"`: positional `name` arg (first onboard) or `--slug` flag (re-onboard),
  `--project` optional. Follow the `"bugs"` `CommandDef` structure with subcommands dict.

**Why:** The CLI surface definition is the single source of truth for help text, shell
completion, and documentation generation. Adding the `CommandDef` before the handler
ensures the surface contract is defined first, and help/usage work immediately.

**Verification:**

- `telec companies --help` prints the onboard subcommand.
- `telec companies onboard --help` prints name/slug/project usage.

- [x] Complete this task

## Task 8: CLI handler — companies onboard command

**File(s):**

- `teleclaude/cli/telec/handlers/companies.py` (new)
- `teleclaude/cli/telec/__init__.py` (modify)

**What:**

`handlers/companies.py`:

- `_handle_companies(args: list[str]) -> None` — route to subcommand handlers.
  Pattern: mirrors `handlers/bugs.py:_handle_bugs()`.
- `_handle_companies_onboard(args: list[str]) -> None` — parse args:
  positional `name` (first onboard), `--slug` (re-onboard), `--project` optional.
  Flow:
  1. Resolve company: `bootstrap_company(name)` if new, `ensure_company_exists(slug)` if re-onboard.
  2. Read meta, scan inbox for new/changed files.
  3. Commit inbox state.
  4. If no new files: print "No new material to process" and return.
  5. Dispatch `/telec-company-analyze` session via `TelecAPIClient.run_session()`
     (same pattern as `handlers/bugs.py:_handle_bugs_report()`).
  6. Print session ID for user to follow.

`__init__.py`:

- Import `_handle_companies` from `handlers.companies`.
- Add dispatch entry: `TelecCommand.COMPANIES: lambda: _handle_companies(args)`.

**Why:** The `TelecAPIClient.run_session()` dispatch pattern is preferred over subprocess
because it integrates with the daemon's session lifecycle (listener registration,
notifications, session tracking). The bugs handler uses this pattern and is the closest
structural parallel — both are CLI commands that scaffold state and dispatch an analysis session.

**Verification:**

- Unit test (xfail → GREEN): `_handle_companies_onboard(["Acme Corp"])` calls `bootstrap_company`
  and dispatches session.
  (`tests/unit/cli/telec/handlers/test_companies.py::test_handle_onboard_new_company_dispatches_session`)
- Unit test (xfail → GREEN): `_handle_companies_onboard(["--slug", "acme"])` calls
  `ensure_company_exists` for re-onboard.
  (`tests/unit/cli/telec/handlers/test_companies.py::test_handle_onboard_reonboard_calls_ensure_exists`)
- Unit test (xfail → GREEN): handler exits early when inbox has no changes.
  (`tests/unit/cli/telec/handlers/test_companies.py::test_handle_onboard_exits_when_no_new_material`)
- Unit test (xfail → GREEN): dispatch constructs correct command/args for `/telec-company-analyze`.
  (`tests/unit/cli/telec/handlers/test_companies.py::test_handle_onboard_dispatch_command_args`)

- [x] Complete this task

## Task 9: Context selection — add company scope tier

**File(s):** `teleclaude/context_selector.py`

**What:**

- Add `"company": 0` to `SCOPE_ORDER` (same precedence level as global — company docs
  are global-in-reach, filtered by membership not priority).
- Modify `_load_selected_snippets()` to load company index alongside global index when
  the project config has a `company` field set:
  1. After loading global index (line 511-516), check if project config has `company`.
  2. If yes, resolve `Path(COMPANIES_ROOT) / slug / COMPANY_DOCS_SUBDIR` as company docs root.
  3. Load its `index.yaml` via `_load_index()` with `source_project="company"`.
  4. Append company snippets to the result list.
  5. If company dir doesn't exist, log a warning and proceed without company docs
     (graceful degradation per design spec).

**Why:** The company tier sits between global and project in the precedence hierarchy.
Adding it to `SCOPE_ORDER` enables the existing merge logic to handle collisions correctly.
Loading the company index in `_load_selected_snippets()` is the minimal integration point —
it reuses `_load_index()` which already handles any snippet root. The graceful degradation
prevents sessions from failing when a company is declared but not yet onboarded.

**Config access pattern:** Read the project config from `project_root` using
`resolve_project_config_path(project_root)` + `load_project_config()` — following the
established `_load_project_domains()` pattern in the same file. Add a `_load_project_company()`
helper that returns `str | None` (the company slug) following the same try/except guard
as `_load_project_domains()`. Pass the result as a parameter into `_load_selected_snippets()`
or read it in the caller and pass `company_slug: str | None = None` to the function.

**Verification:**

- Unit test (xfail → GREEN): company snippets appear in context when project has matching `company` config.
  (`tests/unit/test_context_selector_company.py::test_company_snippets_loaded_when_project_config_matches`)
- Unit test (xfail → GREEN): company snippets absent when project has no `company` config.
  (`tests/unit/test_context_selector_company.py::test_company_snippets_absent_when_no_config`)
- Unit test (xfail → GREEN): company snippets absent when project has a different `company` slug.
  (`tests/unit/test_context_selector_company.py::test_company_snippets_absent_for_wrong_slug`)
- Unit test (xfail → GREEN): missing company directory logs warning, does not fail.
  (`tests/unit/test_context_selector_company.py::test_missing_company_dir_logs_warning_and_continues`)
- Unit test (xfail → GREEN): `SCOPE_ORDER["company"]` equals 0.
  (`tests/unit/test_context_selector_company.py::test_company_scope_order_is_global_level`)

- [x] Complete this task

## Task 10: Index building — include company doc directories

**File(s):** `teleclaude/docs_index.py`

**What:** Modify `build_all_indexes()` to scan company doc directories after project roots:

1. After the existing `iter_snippet_roots()` loop (line 614), scan
   `Path(COMPANIES_ROOT)` for company directories.
2. For each company dir that has a `docs/` subdirectory with snippets, call
   `write_index_yaml(company_dir, company_dir / COMPANY_DOCS_SUBDIR)` to generate its
   `index.yaml`. Pass `company_dir` as `project_root` and `company_dir / COMPANY_DOCS_SUBDIR`
   as `snippets_root`.
3. `write_index_yaml()` already accepts any snippet root — no changes needed to it.

**Why:** Company snippets need `index.yaml` files for the context selector to discover
them. The `build_all_indexes()` function is the central entry point for all index
generation — extending it here means `telec sync` automatically indexes company docs.
`write_index_yaml()` is already generic enough to handle any snippet root path.

**`project_root` rationale for company context:** `build_index_payload()` uses
`project_root` for three purposes: (1) relative path computation (`snippets_root.relative_to(project_root)`)
for `include_baseline` and `is_global` detection; (2) `get_project_name(project_root)` for
`source_project` assignment; (3) file-level path relativization for the `path` field in each
snippet entry. Passing `company_dir` satisfies all three correctly:

- `snippets_root.relative_to(company_dir)` = `"docs"` → `include_baseline = False`,
  `is_global = False` (neither matches `"docs/global"` or `"agents/docs"`) ✓
- `get_project_name(company_dir)` falls back to `company_dir.name` (the slug, since company
  dirs have no `teleclaude.yml`) → `source_project` equals the company slug ✓
- File paths inside `company_dir/docs/` relativize successfully to `company_dir` ✓
- `check_global_collisions` returns early (rel path `"docs"` ≠ `"docs/global"`) — no false
  collision alerts ✓

Passing the TeleClaude project root instead would assign the wrong `source_project` (project
name instead of company slug) and potentially produce incorrect relative paths.

**Verification:**

- Unit test (xfail → GREEN): `build_all_indexes()` discovers company doc directories and
  writes `index.yaml` with `source_project` matching the company slug.
  (`tests/unit/test_docs_index_company.py::test_build_all_indexes_writes_company_index`)
- Unit test (xfail → GREEN): generated `index.yaml` in company docs is well-formed with
  correct snippets.
  (`tests/unit/test_docs_index_company.py::test_company_index_payload_is_well_formed`)
- Unit test (xfail → GREEN): empty company docs dir produces empty (or absent) index, no crash.
  (`tests/unit/test_docs_index_company.py::test_empty_company_docs_produces_no_index`)
- Unit test (xfail → GREEN): multiple companies each get their own `index.yaml`.
  (`tests/unit/test_docs_index_company.py::test_multiple_companies_each_get_own_index`)

- [x] Complete this task

## Task 11: Sync integration — validate company snippets

**File(s):** `teleclaude/sync.py`

**What:** In `sync()`, after `validate_all_snippets(project_root)` (line 45), add a
call to validate company snippet directories. Use `validate_all_snippets()` for each
company dir's `docs/` root — the function already validates any snippet root against
the schema.

**Why:** Without validation integration, invalid company snippets would silently pass
through `telec sync`. Including them in the validation phase catches frontmatter errors,
ID format violations, and schema mismatches before they reach the context selector.

**Verification:**

- Unit test (xfail → GREEN): sync validates company snippets alongside global/project snippets.
  (`tests/unit/test_sync_company.py::test_sync_validates_company_snippets`)
- Unit test (xfail → GREEN): invalid company snippet (wrong frontmatter) produces validation error.
  (`tests/unit/test_sync_company.py::test_sync_reports_error_for_invalid_company_snippet`)
- Regression: existing sync behavior for global/project snippets unchanged.

- [x] Complete this task

## Task 12: Command artifact — `/telec-company-analyze`

**File(s):** `agents/commands/telec-company-analyze.md` (new)

**What:** Create the command artifact following the `telec-init-analyze.md` pattern:

- Required reads: `general/spec/company-scaffolding`, `general/procedure/company-onboarding`,
  `general/spec/snippet-authoring-schema`.
- Steps: read meta.yaml → list/classify input files → map to taxonomy → generate snippets
  with correct frontmatter → validate via `telec sync --validate-only` → report results.
- Discipline: concrete findings only, no generic templates, human edits survive.
- The command uses `company_setup.enrichment` functions for writing snippets.

**Why:** The command artifact is what the dispatched analysis session executes. It must
reference the company-specific specs (scaffolding, onboarding procedure) so the AI agent
follows the correct snippet ID conventions, frontmatter requirements, and merge rules.
The structure mirrors `telec-init-analyze.md` because the analysis workflow is parallel.

**Verification:**

- `telec sync --validate-only` passes with the new artifact present.

- [x] Complete this task

---

## Review Lane Anticipation

| DoD Gate       | Triggered By               | Plan Coverage                                                                                                                                                                                                                         |
| -------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Functionality  | All tasks                  | Each task has behavioral verification                                                                                                                                                                                                 |
| Code quality   | Tasks 3, 4, 5, 6, 8, 9, 10 | Follows existing patterns, explicit types, narrow interfaces                                                                                                                                                                          |
| Testing        | All tasks                  | TDD per task, regression guard on extraction (Task 3)                                                                                                                                                                                 |
| Linting        | All code tasks             | Pre-commit hooks enforced                                                                                                                                                                                                             |
| Security       | Task 8, 9                  | No secrets in company docs, company slug is simple string match (no auth layer per design spec)                                                                                                                                       |
| Documentation  | Task 7, 12                 | CLI help text via surface.py, command artifact for analysis session                                                                                                                                                                   |
| Commit hygiene | All tasks                  | Atomic commits per logical task group                                                                                                                                                                                                 |
| Observability  | Tasks 8, 9, 10, 11         | Logging at key decision points (company resolution, missing dirs, dispatch)                                                                                                                                                           |
| Config surface | Task 1                     | `company` field documented in CLI help; config wizard exposure not needed (field is project-level in teleclaude.yml, not interactive config). `config.sample.yml` update needed: add `company: <slug>` example under project section. |
| Demo           | Pre-existing               | `todos/companies-onboard/demo.md` exists with 7 executable blocks covering bootstrap, directory verification, re-onboard, context selection, isolation, and sync validation. No updates needed from this plan.                        |

## Deferred Items

None. All 8 phases from the input are covered in this plan.
