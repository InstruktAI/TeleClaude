# Implementation Plan: agent-cli-context-preservation

## Overview

Six requirements ship as one coherent delivery: rename the agent CLI configurator module
(R1, R2), add a repo-owned compaction prompt source (R3), deploy it through the configurator
(R4), wrap markdown distribution outputs with context-preservation markers (R5), and clean
up prototype files (R6). Tests are updated throughout (R7).

The rename is a prerequisite for every other change; all tasks after Phase 1 depend on the
new module name.

---

## Phase 1: Module rename (R1, R2)

### Task 1.1: Rename the Python configurator module

**Files:**

- `teleclaude/install/install_hooks.py` → `teleclaude/install/configure_agent_cli.py`

- [x] Copy `install_hooks.py` to `configure_agent_cli.py`
- [x] Update the module docstring to reflect the new name and scope
- [x] Remove `teleclaude/install/install_hooks.py` from disk

**Tests made GREEN:** `test_configure_agent_cli_module_is_importable`, `test_configure_codex_callable_from_renamed_module`, `test_configure_claude_and_gemini_callable_from_renamed_module`, `test_install_hooks_module_no_longer_exists_on_disk`

### Task 1.2: Update all import and reference sites

**Files:**

- `teleclaude/project_setup/init_flow.py`
- `tools/lint/guardrails.py`
- Any other site importing from `teleclaude.install.install_hooks`

- [x] Change `from teleclaude.install import install_hooks` → `configure_agent_cli` in `init_flow.py`
- [x] Update the guardrails exclusion list path from `install_hooks.py` to `configure_agent_cli.py`
- [x] Search repo for remaining references to `install_hooks` and update them

**Tests made GREEN:** `test_init_flow_imports_renamed_module`, `test_guardrails_exclusion_list_references_renamed_module`

### Task 1.3: Rename the CLI entry point and inline the shell wrapper (R2)

**Files:**

- `bin/init/install_hooks.py` → `bin/init/configure_agent_cli.py`
- `bin/init/setup_agent_hooks.sh` (to be removed)
- `bin/init.sh`

- [x] Rename `bin/init/install_hooks.py` to `bin/init/configure_agent_cli.py`; update its import to use `configure_agent_cli`
- [x] In `bin/init.sh`, replace the sourcing of `setup_agent_hooks.sh` with a direct `python` invocation of `bin/init/configure_agent_cli.py` (same PYTHONPATH + venv pattern)
- [x] Remove `bin/init/setup_agent_hooks.sh`

**Tests made GREEN:** `test_bin_init_entry_point_no_longer_exists_at_old_path`, `test_setup_agent_hooks_shell_script_removed`, `test_bin_init_does_not_source_removed_script`, `test_bin_init_invokes_renamed_python_entry_point`

### Task 1.4: Rename the test file

**Files:**

- `tests/unit/install/test_install_hooks.py` → `tests/unit/install/test_configure_agent_cli.py` (merge)

- [x] Move content of `test_install_hooks.py` into the spec file `test_configure_agent_cli.py`, updating the import to `from teleclaude.install import configure_agent_cli`
- [x] Remove the old `test_install_hooks.py`

**Verification:** All Phase 1 module-import tests in `test_configure_agent_cli.py` resolve without ImportError (they inherit from the rename completed in Tasks 1.1–1.3).

---

## Phase 2: Repo-owned compaction prompt and deployment (R3, R4)

### Task 2.1: Add the compaction prompt source file

**File:** `teleclaude/install/settings/CODEX.compaction.md`

- [x] Create `teleclaude/install/settings/CODEX.compaction.md`
- [x] Content: instruct Codex to preserve verbatim all content between `<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->` and `<!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->` markers across compaction cycles

**Tests made GREEN:** `test_compaction_prompt_source_file_exists_in_settings`, `test_compaction_prompt_instructs_preservation_of_marked_content`

### Task 2.2: Register the prompt path in the codex settings override

**File:** `teleclaude/install/settings/codex.json`

- [x] Add `"experimental_compact_prompt_file": "CODEX.compaction.md"` to `teleclaude/install/settings/codex.json`
- [x] The value is the filename (not an absolute path); `configure_codex` resolves it relative to `~/.codex/` at deploy time

**Tests made GREEN (partial):** `test_compact_prompt_key_sourced_from_settings_override` (settings assertion only — full end-to-end assertion requires Task 2.3).

### Task 2.3: Implement compaction prompt deployment in configure_codex

**File:** `teleclaude/install/configure_agent_cli.py`

- [x] In `configure_codex`, after the notify hook and before writing `config.toml`: copy `CODEX.compaction.md` from `teleclaude/install/settings/` to `~/.codex/CODEX.compaction.md`
- [x] The `_apply_codex_settings_overrides` mechanism then picks up `experimental_compact_prompt_file` from `settings/codex.json` and writes it into `config.toml`
- [x] Verify the copy is idempotent (overwrite; content is stable)

**Tests made GREEN:** `test_configure_codex_writes_compaction_prompt_to_codex_dir`, `test_configure_codex_sets_compact_prompt_toml_key`, `test_configure_codex_compaction_prompt_deployment_is_idempotent`, `test_compact_prompt_key_sourced_from_settings_override` (end-to-end assertion).

---

## Phase 3: Context-preservation markers in distribution output (R5)

### Task 3.1: Add wrap_with_context_markers helper

**File:** `scripts/distribute.py`

- [x] Add `CONTEXT_PRESERVATION_START = "<!-- TELECLAUDE_CONTEXT_PRESERVATION_START -->"` and `CONTEXT_PRESERVATION_END = "<!-- TELECLAUDE_CONTEXT_PRESERVATION_END -->"` constants
- [x] Add `wrap_with_context_markers(content: str, *, is_markdown: bool) -> str` that returns the content unchanged when `is_markdown=False`, or wrapped with the start/end markers (with a newline separator) when `is_markdown=True`

**Tests made GREEN:** `test_markdown_wrapped_content_contains_start_marker`, `test_markdown_wrapped_content_contains_end_marker`, `test_start_marker_precedes_content_body`, `test_end_marker_follows_content_body`, `test_toml_content_not_wrapped_with_markers`, `test_original_content_preserved_inside_markers`

### Task 3.2: Apply wrapping at the markdown serializer level

**File:** `scripts/distribute.py`

**Rationale:** The approved test specs (`test_claude_transform_output_contains_preservation_markers`,
`test_codex_transform_output_contains_preservation_markers`) call `dump_frontmatter` and
`transform_to_codex` directly, bypassing `_run_phase`. Wrapping at `_run_phase` level cannot
satisfy those tests. `dump_frontmatter` is the sole markdown serializer for Claude and Codex
formats; wrapping there propagates automatically to all callers including `transform_to_codex`
(which calls `dump_frontmatter` at line 231).

- [x] In `dump_frontmatter`, apply `wrap_with_context_markers(content, is_markdown=True)` to the
      return value before returning
- [x] Verify: `transform_to_codex` output inherits markers via its `dump_frontmatter` call
- [x] Verify: `transform_to_gemini` output (TOML) does not call `dump_frontmatter` and is therefore unwrapped

**Tests made GREEN:** `test_claude_transform_output_contains_preservation_markers`,
`test_codex_transform_output_contains_preservation_markers`

---

## Phase 4: Remove prototype files (R6)

### Task 4.1: Delete prototype .codex files

**Files:**

- `.codex/config.toml`
- `.codex/CODEX.compaction.md`

- [x] Delete `.codex/config.toml` from the repository
- [x] Delete `.codex/CODEX.compaction.md` from the repository
- [x] Confirm no committed references to these paths remain (`git grep .codex`)

**Tests already active (must stay GREEN):** `test_prototype_codex_config_toml_not_in_repository`, `test_prototype_codex_compaction_md_not_in_repository`

---

## Phase 5: Tests and quality gates (R7)

### Task 5.1: Activate spec tests

- [x] Remove `@pytest.mark.xfail` markers from `tests/unit/install/test_configure_agent_cli.py` as each R1/R2/R3/R4 behavior is satisfied
- [x] Remove `@pytest.mark.xfail` markers from `tests/unit/scripts/test_distribute.py` as each R5 behavior is satisfied

### Task 5.2: Quality checks

- [x] Run `make lint` (ruff + pylint import-outside-toplevel)
- [x] Run `make test` via pre-commit hooks
- [x] Confirm all expected-failure markers are removed — suite is fully green
- [x] Confirm `bin/init/setup_agent_hooks.sh` is absent (`ls bin/init/`)
- [x] Confirm `.codex/config.toml` and `.codex/CODEX.compaction.md` are absent (`git status`)

**Notes:**

- `make lint` passed after normalizing repo doc-snippet references from absolute `/Users/Morriz/.teleclaude/docs/...` paths to `~/.teleclaude/docs/...` and aligning `tools/lint.sh` with the repo's intended Pylint `import-outside-toplevel` gate.
- `make test` passed with session-scoped coverage of the changed install, distribution, and init-flow tests.
- `telec todo demo validate agent-cli-context-preservation` passed with 8 executable bash blocks.
- Repo-local prototype files are gone. Remaining `.codex` hits are expected runtime references to `~/.codex/...`, third-party docs, and task-local verification artifacts.

---

## Phase 6: Demo and verification (execution post-merge)

### Task 6.1: Populate demo.md with executable verification blocks

**File:** `todos/agent-cli-context-preservation/demo.md`

**Rationale:** The demo provides executable proof that the delivery works end-to-end. After merge
to main, `telec todo demo run agent-cli-context-preservation` executes these blocks to validate
all requirements.

**Verification:** All blocks execute successfully and produce expected output.

- [x] Add bash blocks to verify:
  1. The renamed module is importable and callable
  2. The compaction prompt file exists in the deployed location
  3. Context preservation markers wrap markdown artifacts in the distribution output
  4. Prototype `.codex/` files are absent from the repo

---

## Phase 7: Review readiness

- [x] All requirements R1–R7 reflected in committed code
- [x] All task checkboxes above marked `[x]`
- [x] demo.md is populated with executable blocks
- [x] No TODOs or FIXMEs without tickets
- [x] Document any deferrals in `deferrals.md`
