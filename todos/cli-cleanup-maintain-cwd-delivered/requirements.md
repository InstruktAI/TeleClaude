# Requirements: cli-cleanup-maintain-cwd-delivered

## Goal

Clean up the telec CLI: remove the dead maintain command, fix --cwd defaults, and add delivered-item visibility to roadmap list.

## Scope

### In scope:

- Full removal of `telec todo maintain` (command, API, auth, skill mapping, state machine)
- Make `--cwd` optional with cwd default on `todo mark-phase` and `todo set-deps`
- Add `--include-delivered` and `--delivered-only` flags to `telec roadmap list`

### Out of scope:

- The `next-maintain` slash command/skill deployed outside this repo (handled separately)
- Future maintenance infrastructure design
- Changes to icebox flags or other roadmap list behavior

## Success Criteria

- [ ] `telec todo maintain` is fully removed — no import, no route, no CLI dispatch, no clearance entry
- [ ] `telec todo mark-phase <slug> --phase build --status complete` works without `--cwd` (defaults to cwd)
- [ ] `telec todo set-deps <slug> --after dep1` works without `--cwd` (defaults to cwd)
- [ ] `telec roadmap list --include-delivered` shows active roadmap items plus delivered items
- [ ] `telec roadmap list --delivered-only` shows only delivered items
- [ ] Delivered items display slug, date, and title/description
- [ ] Pattern mirrors `--include-icebox` / `--icebox-only` convention
- [ ] All existing tests pass (`make test`)
- [ ] Linting passes (`make lint`)

## Constraints

- Delivered output must use `todos/delivered.yaml` as the data source
- `--cwd` flag must remain accepted for backward compatibility, just not required

## Risks

- None significant — all changes are additive or removal of dead code
