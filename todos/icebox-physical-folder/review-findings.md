# Review Findings: icebox-physical-folder

## Verdict: APPROVE

**Reviewer:** Claude (automated review)
**Scope:** All commits on `icebox-physical-folder` branch since divergence from `main`
**Changed files:** 13 (6 production, 5 test, 2 demo)

---

## Resolved During Review

### 1. `shutil.move` destination-exists nesting bug (Important → Resolved)

**Location:** `teleclaude/core/next_machine/core.py:1861`, `:1890`, `:1930`

**Issue:** When `shutil.move(src, dest)` is called and `dest` is an existing directory,
Python moves `src` *inside* `dest`, creating a nested `slug/slug/` layout instead of
replacing. This silently corrupts the directory structure. Affected all three new
`shutil.move` call sites: `freeze_to_icebox`, `unfreeze_from_icebox`, and
`migrate_icebox_to_subfolder`.

**Fix applied:** Added destination-existence guards:
- `freeze_to_icebox`: raises `FileExistsError` if `_icebox/{slug}` already exists
- `unfreeze_from_icebox`: raises `FileExistsError` if `todos/{slug}` already exists
- `migrate_icebox_to_subfolder`: skips already-migrated folders (`not dest.exists()`)

All tests pass after fix.

---

## Suggestions (non-blocking)

### S1. `_handle_roadmap_migrate_icebox` silently ignores extra arguments

**Location:** `teleclaude/cli/telec.py:3109-3118`

The handler accepts `args` but never validates them. Unlike sibling handlers (`freeze`,
`unfreeze`) which reject unknown options, `migrate-icebox` silently ignores any arguments.
A user typing `telec roadmap migrate-icebox --force` gets no feedback that the flag was
ignored.

### S2. Migration could be more robust about concurrent manifests

**Location:** `teleclaude/core/next_machine/core.py:1933`

If both `todos/icebox.yaml` (old) and `todos/_icebox/icebox.yaml` (new) exist
simultaneously — e.g., a freeze happened after code deploy but before migration — the
old manifest overwrites the new one. In practice, this is a single-operator one-time
operation, so the risk is low.

### S3. Test coverage gaps (all low-effort)

- `validate_all_todos` `_icebox` skip (`resource_validation.py:1153`) has zero test
  coverage. The entire function is untested (pre-existing gap), but the new skip would
  benefit from a regression guard.
- No test for `unfreeze_from_icebox` without a physical folder (symmetry with existing
  `test_freeze_without_folder_succeeds`).
- No test for migration with entries that have no corresponding folders.
- Near-duplicate test `test_is_slug_frozen_via_new_icebox_yaml_path` adds minimal value
  over the updated existing test.

### S4. Migration reads raw YAML instead of `load_icebox`

**Location:** `teleclaude/core/next_machine/core.py:1917`

`migrate_icebox_to_subfolder` uses `yaml.safe_load(old_manifest.read_text())` directly
instead of `load_icebox()`. This is intentional (migration must read from the old path
while `load_icebox` reads from the new path), but it bypasses encoding handling
(`read_text()` without explicit encoding vs `read_text_sync`).

---

## Review Lane Summary

| Lane | Result | Notes |
|------|--------|-------|
| Scope | PASS | All 7 requirements implemented, no gold-plating. `resource_validation.py` change is a necessary adaptation. |
| Code | PASS | Pattern consistency with existing freeze/deliver handlers. CLI registration correct. |
| Paradigm | PASS | Data flow uses established `load_*/save_*` layer. Component reuse follows adjacent code. |
| Principles | PASS | No unjustified fallbacks. Orphan scan uses `== "_icebox"` (not `startswith`). SRP maintained. |
| Security | PASS | No secrets, no injection, no info leakage. Auth level matches freeze. |
| Tests | PASS | Core behaviors tested: freeze/unfreeze folder moves, migration, remove from icebox, orphan scan, CLI handlers. Minor gaps noted in S3. |
| Errors | PASS | Pre-existing patterns (load_icebox `[]` return, non-atomic writes) noted but not introduced by this PR. New `shutil.move` nesting bug fixed inline. |
| Demo | PASS | All commands exist, blocks are executable, guided presentation covers all features. |
| Docs | PASS | CLI help auto-generated from CLI_SURFACE. No config surface changes. |

## Why No Critical/Important Issues Remain

1. **Paradigm-fit verified:** New functions follow established `freeze_to_icebox` pattern.
   CLI handlers mirror `_handle_roadmap_freeze`. `is_icebox_item` parameter addition is
   minimal and cohesive with `assemble_roadmap`'s existing closure-based architecture.
2. **Requirements met:** Each R1-R7 has corresponding implementation verified against the
   diff. No unrequested features.
3. **Copy-paste duplication checked:** `_handle_roadmap_unfreeze` mirrors freeze handler —
   this is intentional structural symmetry, not accidental duplication. Core functions
   share no copy-pasted logic.
4. **Security reviewed:** No user-controlled input reaches filesystem paths without prior
   YAML validation (slug must exist in roadmap/icebox entries).
