# Implementation Plan: icebox-physical-folder

## Summary

Move frozen todo folders from `todos/` to `todos/_icebox/`, relocate `icebox.yaml`
into the same directory, add folder-move logic to freeze/unfreeze, and adapt the
orphan scan and removal to the new layout.

Estimated change: ~250 lines across 5 production files plus targeted test/demo
updates. Single builder session.

---

## Tasks

### T1 — Update `_icebox_path()` to new location

**What:** Change `_icebox_path()` in `teleclaude/core/next_machine/core.py:1731` to
return `Path(cwd) / "todos" / "_icebox" / "icebox.yaml"`.

**Why:** All icebox YAML consumers (`load_icebox`, `save_icebox`, `load_icebox_slugs`,
`remove_from_icebox`, `freeze_to_icebox`, `clean_dependency_references`) call through
this single path function. Changing it once propagates the new location to all
consumers with zero per-consumer patching.

**Files:**
- `teleclaude/core/next_machine/core.py` — `_icebox_path()` (line 1731)

**Verification:** Unit test: `_icebox_path("foo")` returns `Path("foo/todos/_icebox/icebox.yaml")`.

---

### T2 — Update `assemble_roadmap()` for the new `_icebox/` layout

**What:** In `teleclaude/core/roadmap.py`:
1. Change `icebox_yaml_path` from `todos_root / "icebox.yaml"` to
   `todos_root / "_icebox" / "icebox.yaml"`.
2. Add `icebox_root = todos_root / "_icebox"`.
3. Refactor `append_todo()` / `read_todo_metadata()` so active items still read from
   `todos/{slug}`, but icebox items loaded from `icebox.yaml` read metadata, files,
   and `state.yaml` from `todos/_icebox/{slug}`.
4. Keep the legacy `icebox.md` fallback unchanged.

**Why:** The manifest existence check is only half the change. After folders move,
`append_todo()` can no longer assume every slug lives directly under `todos/`.
If this task only changes the YAML path, `telec roadmap list --include-icebox` still
finds the slugs but silently drops their real files, requirements, and status because
it looks in the wrong directory.

**Files:**
- `teleclaude/core/roadmap.py` — manifest path check and icebox metadata sourcing

**Verification:** New test: with a real `_icebox/icebox.yaml` file and
`todos/_icebox/icebox-item/state.yaml`, `assemble_roadmap(..., include_icebox=True)`
returns the icebox item with its real metadata. Update roadmap API parity fixtures to
create the manifest at the new path so the existing chain tests still exercise the
icebox branch.

---

### T3 — Add `_icebox_dir()` helper and folder-move to `freeze_to_icebox()`

**What:**
1. Add `_icebox_dir(cwd: str) -> Path` returning `Path(cwd) / "todos" / "_icebox"`.
2. In `freeze_to_icebox()` (core.py:1827), after the existing YAML update, add:
   - `_icebox_dir(cwd).mkdir(parents=True, exist_ok=True)`
   - Move `todos/{slug}/` to `todos/_icebox/{slug}/` using `shutil.move`.
   - Guard: if source folder doesn't exist, skip the move (YAML-only freeze is valid).

**Why:** The freeze operation must be atomic — YAML state and physical location must
stay in sync. Moving the folder alongside the YAML update prevents the stale state
where `icebox.yaml` says frozen but the folder sits in `todos/`. The guard for
missing source handles icebox entries without folders (e.g., `agent-file-locking-heartbeat`).

**Files:**
- `teleclaude/core/next_machine/core.py` — new `_icebox_dir()`, modified `freeze_to_icebox()`

**Verification:** Unit test: freeze a slug with a folder → folder moves to `_icebox/`.
Unit test: freeze a slug without a folder → succeeds without error.

---

### T4 — New `unfreeze_from_icebox()` function

**What:** Add `unfreeze_from_icebox(cwd: str, slug: str) -> bool` in
`teleclaude/core/next_machine/core.py`, placed after `freeze_to_icebox()`:
1. Load icebox entries, find and remove the matching entry.
2. If not found, return `False`.
3. Save updated icebox.
4. Load roadmap, append the entry, save roadmap.
5. Move `todos/_icebox/{slug}/` to `todos/{slug}/` (guard: skip if source doesn't exist).
6. Return `True`.

**Why:** Symmetry with `freeze_to_icebox`. The unfreeze operation must also keep YAML
and folder location in sync. Appending to roadmap (not prepending) places unfrozen
items at lowest priority, matching the mental model of "promote back when priority
changes".

**Files:**
- `teleclaude/core/next_machine/core.py` — new `unfreeze_from_icebox()`

**Verification:** Unit test: unfreeze a frozen slug → entry moves from icebox.yaml to
roadmap.yaml, folder moves from `_icebox/` to `todos/`. Unit test: unfreeze a
non-existent slug → returns False.

---

### T5 — Register `telec roadmap unfreeze` CLI command

**What:**
1. Add `"unfreeze"` to `CLI_SURFACE` roadmap subcommands (after `"freeze"`):
   ```python
   "unfreeze": CommandDef(
       desc="Promote entry from icebox to roadmap",
       args="<slug>",
       flags=[],
       auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
   ),
   ```
2. Add `elif subcommand == "unfreeze":` dispatch in `_handle_roadmap()` (after freeze).
3. Add `_handle_roadmap_unfreeze()` handler following the `_handle_roadmap_freeze()`
   pattern: parse slug, call `unfreeze_from_icebox()`, print confirmation or error.

**Why:** CLI registration follows the established pattern. Auth level matches freeze
(same actor should be able to both freeze and unfreeze). The handler is a mirror of
the freeze handler — same argument parsing, same error handling.

**Files:**
- `teleclaude/cli/telec.py` — `CLI_SURFACE`, `_handle_roadmap()`, new `_handle_roadmap_unfreeze()`

**Verification:** `telec roadmap unfreeze test-slug` prints
`"Unfroze test-slug → roadmap.yaml"`. Missing slug prints usage. Non-existent slug
prints error and exits 1. Add unit coverage for the handler/help path in
`tests/unit/test_telec_cli.py`.

---

### T6 — Update `assemble_roadmap()` orphan scan to skip `_icebox`

**What:** In the orphan scan loop (`roadmap.py:248`), add an explicit name check:
```python
if todo_dir.name == "_icebox":
    continue
```
Place this after the `.startswith(".")` check (line 251) and before the `seen_slugs`
check.

**Why:** Without this, `_icebox` would appear as an orphan todo in roadmap listings.
The requirement explicitly specifies `== "_icebox"` (not `startswith("_")`) to avoid
accidentally excluding future underscore-prefixed directories.

**Files:**
- `teleclaude/core/roadmap.py` — orphan scan loop (around line 248-252)

**Verification:** Unit test: `_icebox` directory exists in `todos/` → not listed as
orphan. Other underscore-prefixed directories are still listed (not excluded).

---

### T7 — Update `remove_todo()` to check `_icebox/` location

**What:** In `remove_todo()` (`todo_scaffold.py:150`), after computing `todo_dir`,
also check `todos/_icebox/{slug}`. If the folder exists there, remove from that
location instead.

Specifically:
```python
todo_dir = todos_root / slug
icebox_dir = todos_root / "_icebox" / slug
# Use whichever exists (prefer active location)
target_dir = todo_dir if todo_dir.exists() else icebox_dir
found_directory = target_dir.exists()
# ... later: shutil.rmtree(target_dir)
```

**Why:** After migration, frozen todo folders live in `_icebox/`. Without this change,
`telec todo remove` would report "not found" for icebox slugs even though the folder
exists. The YAML removal already works (it reads `icebox.yaml` via `_icebox_path()`
which T1 updated).

**Files:**
- `teleclaude/todo_scaffold.py` — `remove_todo()` (around line 186-198)

**Verification:** Unit test: remove a frozen slug with folder in `_icebox/` → folder
deleted, icebox entry removed.

---

### T8 — Update frozen-slug detection to the relocated manifest

**What:** In `teleclaude_events/cartridges/prepare_quality.py`, replace the hardcoded
`project_root / "todos" / "icebox.yaml"` read inside `_is_slug_delivered_or_frozen()`
with helper-based loading that follows T1 (prefer `load_icebox(str(project_root))`
instead of another ad hoc path). Keep the legacy `icebox.md` fallback.

**Why:** Prepare-quality uses frozen-state detection to prevent work from being
prepared against parked items. If it keeps reading the old path after migration,
frozen slugs become incorrectly eligible for preparation even though the roadmap has
already moved them into `_icebox/`.

**Files:**
- `teleclaude_events/cartridges/prepare_quality.py` — `_is_slug_delivered_or_frozen()`

**Verification:** Unit test: a slug present in `todos/_icebox/icebox.yaml` returns
`True` from `_is_slug_delivered_or_frozen()`.

---

### T9 — One-time migration function + CLI command

**What:** Add `migrate_icebox_to_subfolder(cwd: str) -> int` in
`teleclaude/core/next_machine/core.py` (in the Icebox Management section):
1. If `todos/icebox.yaml` doesn't exist but `todos/_icebox/icebox.yaml` does,
   return 0 (already migrated).
2. Create `todos/_icebox/` if needed.
3. Read slugs + groups from `todos/icebox.yaml`.
4. For each slug/group with a folder in `todos/`, move to `todos/_icebox/`.
5. Move `todos/icebox.yaml` to `todos/_icebox/icebox.yaml`.
6. Return count of items moved.

Expose via CLI as `telec roadmap migrate-icebox` with a simple handler.

**Why:** 17 entries need migration (16 slug folders + 1 group container). An
idempotent helper ensures consistency. Making the migration explicit via CLI is safer
than burying filesystem mutation inside a read path like `load_icebox()` or
`assemble_roadmap()`: the operator gets a contained one-shot action instead of a
hidden side effect on normal roadmap access.

**Files:**
- `teleclaude/core/next_machine/core.py` — new `migrate_icebox_to_subfolder()`
- `teleclaude/cli/telec.py` — new `"migrate-icebox"` subcommand under roadmap

**Verification:** Unit test: mock icebox with 3 folders → migrate → folders in
`_icebox/`, old `icebox.yaml` gone. Run again → returns 0 (idempotent).

---

### T10 — Update targeted tests and refresh the demo artifact

**What:** Update and add tests:

1. **Update existing roadmap tests** in `tests/unit/core/test_roadmap.py` and
   `tests/unit/core/test_roadmap_api_parity.py`:
   - Fixtures that touch `todos/icebox.yaml` must instead create
     `todos/_icebox/icebox.yaml`.
   - Frozen-item fixtures must place folders and `state.yaml` under `_icebox/{slug}`
     when verifying include-icebox behavior.

2. **Update existing todo scaffolding tests** in `tests/unit/test_todo_scaffold.py`:
   - `test_remove_todo_removes_from_icebox`: after freeze, folder should be in
     `_icebox/`.
   - `test_remove_todo_cleans_up_dependency_references`: same path adjustment.

3. **Add CLI coverage** in `tests/unit/test_telec_cli.py`:
   - `roadmap unfreeze` prints confirmation, handles missing slug, and exits 1 for
     unknown slugs.
   - `roadmap migrate-icebox` handler reports moved count and remains idempotent.

4. **Update frozen-state tests** in
   `tests/unit/test_teleclaude_events/test_prepare_quality.py` to point at
   `_icebox/icebox.yaml`.

5. **Refresh `demo.md`** so the executable blocks use valid current CLI syntax
   (`--description`, not `--desc`) and a valid slug format (`demo-freeze-test`, not a
   leading-underscore slug). Keep the demo focused on migration, freeze, unfreeze,
   remove, and orphan-scan validation.

6. **New behavior tests** (can live in the files above):
   - `test_icebox_path_returns_new_location` — verify `_icebox_path` output.
   - `test_freeze_moves_folder_to_icebox` — folder physically moves.
   - `test_freeze_without_folder_succeeds` — YAML-only freeze.
   - `test_unfreeze_moves_folder_back` — folder returns to `todos/`.
   - `test_unfreeze_nonexistent_slug_returns_false`.
   - `test_assemble_roadmap_reads_icebox_metadata_from_subfolder` — include-icebox
     items retain state/files from `_icebox/{slug}`.
   - `test_orphan_scan_skips_icebox_dir` — `_icebox` not listed as orphan.
   - `test_orphan_scan_does_not_skip_other_underscore_dirs` — specificity check.
   - `test_remove_todo_from_icebox_location` — removal from `_icebox/`.
   - `test_prepare_quality_detects_frozen_slug_in_new_manifest_path`.
   - `test_migrate_icebox_moves_folders` — migration correctness.
   - `test_migrate_icebox_idempotent` — double-run safety.

**Why:** Tests and demo must reflect the new layout. Existing tests that hardcode the
old manifest path will fail after T1/T2/T8 if not updated. The CLI and demo are
user-facing surfaces, so they need explicit coverage rather than relying on the core
tests to catch regressions indirectly.

**Files:**
- `tests/unit/core/test_roadmap.py`
- `tests/unit/core/test_roadmap_api_parity.py`
- `tests/unit/test_todo_scaffold.py`
- `tests/unit/test_telec_cli.py`
- `tests/unit/test_teleclaude_events/test_prepare_quality.py`
- `todos/icebox-physical-folder/demo.md`

**Verification:** Run the smallest proving set:
`pytest tests/unit/core/test_roadmap.py tests/unit/core/test_roadmap_api_parity.py tests/unit/test_todo_scaffold.py tests/unit/test_telec_cli.py tests/unit/test_teleclaude_events/test_prepare_quality.py`
and `telec todo demo validate icebox-physical-folder`. Before commit, run the
repository pre-commit hooks as the primary final gate so lint/type/test checks
also pass beyond the targeted proving set used during development.

---

## Task order

```
T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10
```

T1 and T2 establish the path foundation. T3-T5 add new behavior. T6-T7 adapt
existing consumers. T8 closes the remaining frozen-state consumer that still reads the
old manifest path. T9 handles migration. T10 wraps with tests and demo validation.

The builder should write tests first (RED) for each task, then implement (GREEN),
per TDD policy.

## Referenced files

- `teleclaude/core/next_machine/core.py`
- `teleclaude/core/roadmap.py`
- `teleclaude/todo_scaffold.py`
- `teleclaude/cli/telec.py`
- `teleclaude_events/cartridges/prepare_quality.py`
- `tests/unit/core/test_roadmap.py`
- `tests/unit/core/test_roadmap_api_parity.py`
- `tests/unit/test_todo_scaffold.py`
- `tests/unit/test_telec_cli.py`
- `tests/unit/test_teleclaude_events/test_prepare_quality.py`
- `todos/icebox-physical-folder/demo.md`
