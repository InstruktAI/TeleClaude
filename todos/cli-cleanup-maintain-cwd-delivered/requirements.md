# Requirements: cli-cleanup-maintain-cwd-delivered

## Goal

Clean up the telec CLI: remove the dead maintain command, fix --cwd defaults, and add delivered-item visibility to roadmap list.

## Scope

### In scope:

- Full removal of `telec todo maintain` (command, API, auth, skill mapping, state machine)
- Remove `--cwd` and `--project-root` from the entire CLI surface (all commands); handlers use `os.getcwd()` unconditionally
- Add `--include-delivered` and `--delivered-only` flags to `telec roadmap list`

### Out of scope:

- The `next-maintain` slash command/skill deployed outside this repo (handled separately)
- Future maintenance infrastructure design
- Changes to icebox flags or other roadmap list behavior

## Success Criteria

- [ ] `telec todo maintain` is fully removed — no import, no route, no CLI dispatch, no clearance entry
- [ ] No CLI command accepts `--cwd` or `--project-root` — flag is fully removed from arg parsing and help text
- [ ] All CLI handlers derive project root from `os.getcwd()` unconditionally
- [ ] Python-level functions still accept `cwd` parameter for API routes and internal callers
- [ ] `telec roadmap list --include-delivered` shows active roadmap items plus delivered items
- [ ] `telec roadmap list --delivered-only` shows only delivered items
- [ ] Delivered items display slug, date, and title/description
- [ ] Pattern mirrors `--include-icebox` / `--icebox-only` convention
- [ ] All existing tests pass (`make test`)
- [ ] Linting passes (`make lint`)

## Constraints

- Delivered output must use `todos/delivered.yaml` as the data source
- Python-level `cwd` parameters on internal functions are untouched — only CLI parsing is removed

## Risks

- None significant — all changes are additive or removal of dead code
