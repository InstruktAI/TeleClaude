# Requirements: icebox-physical-folder

## Goal

Frozen todos should live in a dedicated `todos/_icebox/` directory so that
`todos/` contains only active/pending work. The icebox manifest moves with
its folders. Freeze/unfreeze commands handle the physical move alongside
the YAML updates.

## In scope

1. Physical folder separation: `todos/_icebox/` as the home for frozen items.
2. `telec roadmap freeze` gains folder-move behavior.
3. New `telec roadmap unfreeze` command (promote from icebox to roadmap).
4. `icebox.yaml` relocates to `todos/_icebox/icebox.yaml`.
5. `assemble_roadmap()` orphan scan and icebox scanning adapt to the new layout.
6. `telec todo remove` checks both locations.
7. One-time migration of existing icebox folders and manifest.

## Out of scope

- Changes to `delivered.yaml` or delivered folder layout.
- TUI rendering changes (the TUI already hides icebox via
  `assemble_roadmap` flags). [inferred]
- Worktree handling for icebox items (icebox items are frozen, not built).
  [inferred]

## Requirements

Code-grounding that comes from the current implementation rather than
`input.md` is marked `[inferred]`.

### R1 — `todos/_icebox/` directory

- All frozen todo folders reside under `todos/_icebox/{slug}/`.
- `todos/_icebox/icebox.yaml` is the icebox manifest (same schema as current
  `todos/icebox.yaml`).
- Active `todos/` contains no frozen-item folders after migration.

### R2 — `_icebox_path()` update [inferred]

- `_icebox_path()` (`core/next_machine/core.py:1731`) returns
  `Path(cwd) / "todos" / "_icebox" / "icebox.yaml"`.
- All consumers of `load_icebox()` / `save_icebox()` follow the relocated
  manifest path through the existing helper instead of adding ad hoc path
  handling.

### R3 — `freeze_to_icebox()` gains folder move [inferred]

- After the existing YAML update (`core/next_machine/core.py:1827–1843`),
  the function moves `todos/{slug}/` to `todos/_icebox/{slug}/`.
- Creates `todos/_icebox/` if it does not exist.
- If the source folder does not exist, the YAML update still succeeds so
  metadata-only icebox entries remain movable.

### R4 — New `telec roadmap unfreeze <slug>` command

- Removes the entry from `icebox.yaml`, adds it to `roadmap.yaml`.
- Moves `todos/_icebox/{slug}/` back to `todos/{slug}/`.
- If the folder does not exist in `_icebox/`, the YAML-only update still
  succeeds. [inferred]
- CLI registration and usage/help follow the existing `telec.py` roadmap
  subcommand pattern (same auth level as `freeze`). [inferred]
- Prints confirmation: `"Unfroze {slug} → roadmap.yaml"`. [inferred]

### R5 — `assemble_roadmap()` orphan and icebox scan [inferred]

- The orphan scan (`core/roadmap.py:247–276`) that walks `todos/` must skip
  `_icebox` using an explicit name check: `todo_dir.name == "_icebox"`.
  Not `startswith("_")`.
- Icebox item scanning reads folder contents from `todos/_icebox/` instead
  of expecting icebox folders to be mixed into `todos/`.

### R6 — `remove_todo()` checks both locations [inferred]

- `remove_todo()` (`todo_scaffold.py:150–202`) must look for the folder in
  both `todos/{slug}` and `todos/_icebox/{slug}`.
- If found in `_icebox`, it deletes from there.
- The existing roadmap/icebox YAML removal and dependency cleanup are
  unaffected.

### R7 — One-time migration

- A one-time migration moves every existing icebox directory currently under
  `todos/` into `todos/_icebox/` and relocates `todos/icebox.yaml` to
  `todos/_icebox/icebox.yaml`.
- The migration is idempotent: running it when folders are already in
  `_icebox` is a no-op.
- The group container folder (`multi-user-system-install`) moves with its
  member folders. [inferred]

## Success criteria

- [ ] `todos/` contains zero folders whose slug appears in
      `todos/_icebox/icebox.yaml`.
- [ ] `telec roadmap freeze <slug>` moves the folder to `_icebox/` and
      updates icebox.yaml at the new path.
- [ ] `telec roadmap unfreeze <slug>` moves the folder back and updates
      both YAML files.
- [ ] `telec roadmap` usage/help exposes the new `unfreeze` subcommand.
- [ ] `telec roadmap list --icebox-only` still lists all icebox items.
- [ ] `telec todo remove <slug>` succeeds for slugs whose folders are in
      `_icebox/`.
- [ ] Orphan scan does not report `_icebox` as an orphan.
- [ ] Orphan scan does not report icebox folders that are now inside
      `_icebox/`.
- [ ] Targeted tests cover freeze/unfreeze folder moves, `_icebox` roadmap
      scanning, `telec todo remove` against frozen folders, and migration
      idempotence.
- [ ] All existing tests pass after changes.
- [ ] The one-time migration is idempotent.

## Constraints

- Orphan scan exclusion uses `todo_dir.name == "_icebox"`, not
  `startswith("_")` (explicit from input).
- Existing `RoadmapEntry` dataclass and icebox.yaml schema are unchanged.
  [inferred]
- `load_icebox()` / `save_icebox()` API is unchanged; only the underlying
  path moves. [inferred]

## Risks

- Worktree copies may have their own `todos/icebox.yaml`. The path change
  must work correctly in worktrees where `cwd` differs from the main repo
  root. [inferred — verify in draft phase]
