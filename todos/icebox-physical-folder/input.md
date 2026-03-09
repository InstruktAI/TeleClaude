# Physical icebox folder for frozen todos

## Problem

Frozen todos stay in `todos/` as dead weight. The TUI hides them (because `assemble_roadmap` filters icebox items by default), so they're invisible yet cluttering the workspace. 18 orphaned folders the user didn't know existed.

Icebox is currently metadata-only (`icebox.yaml`). Folder location doesn't reflect status.

## Desired behavior

- `todos/_icebox/` holds all frozen todo folders physically
- `todos/` contains only active/pending work
- `telec roadmap freeze <slug>` moves the folder from `todos/{slug}` to `todos/_icebox/{slug}` (in addition to the YAML updates)
- `telec roadmap unfreeze <slug>` (new command) moves the folder back from `todos/_icebox/{slug}` to `todos/{slug}`, removes from `icebox.yaml`, adds to `roadmap.yaml`
- `icebox.yaml` moves to `todos/_icebox/icebox.yaml`
- `telec todo remove` checks both `todos/{slug}` and `todos/_icebox/{slug}`
- `assemble_roadmap()` orphan scan skips `_icebox` by explicit name check (not `startswith("_")`)
- `assemble_roadmap()` icebox item scanning reads from `todos/_icebox/` directory
- One-time migration: move all 18 existing icebox folders + `icebox.yaml` into `todos/_icebox/`

## Explicit constraint

- Orphan scan exclusion: use explicit `todo_dir.name == "_icebox"` check, not `startswith("_")`
