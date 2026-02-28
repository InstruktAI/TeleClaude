# Requirements: cli-cleanup-maintain-cwd-delivered

## Goal

Clean up the telec CLI: remove the dead maintain command, fix --cwd defaults, and add delivered-item visibility to roadmap list.

## Scope

### In scope:

- Full removal of `telec todo maintain` (command, API, auth, skill mapping, state machine)
- Remove `--cwd` and `--project-root` from the entire CLI surface (telec.py, config_cmd.py, tool_commands.py); handlers use `os.getcwd()` unconditionally
- Fix internal subprocess callers (watch.py, next_machine/core.py) that pass `--project-root` to `telec` — they already set `cwd=`, just drop the flag
- Migrate tests from `--project-root` to `monkeypatch.chdir`
- Add `--include-delivered` and `--delivered-only` flags to `telec roadmap list`

### Out of scope:

- The `next-maintain` slash command/skill deployed outside this repo (handled separately)
- Future maintenance infrastructure design
- Changes to icebox flags or other roadmap list behavior
- Standalone scripts with own argparse (`scripts/distribute.py`, `teleclaude/entrypoints/macos_setup.py`, `tools/migrations/migrate_requires.py`)

## Success Criteria

- [ ] `telec todo maintain` is fully removed — no import, no route, no CLI dispatch, no clearance entry
- [ ] No CLI command accepts `--cwd` or `--project-root` — flag is fully removed from arg parsing and help text
- [ ] All CLI handlers derive project root from `os.getcwd()` unconditionally
- [ ] Internal subprocess callers (`watch.py`, `next_machine/core.py`) no longer pass `--project-root` to `telec`
- [ ] Python-level functions still accept `cwd` parameter for API routes and internal callers
- [ ] Standalone scripts (`distribute.py`, `macos_setup.py`, `migrate_requires.py`) are untouched
- [ ] `telec roadmap list --include-delivered` shows active roadmap items plus delivered items
- [ ] `telec roadmap list --delivered-only` shows only delivered items
- [ ] `TodoInfo` carries `delivered_at: Optional[str]` — lifecycle date for delivered items
- [ ] Delivered items display slug, delivery date, and title/description
- [ ] Pattern mirrors `--include-icebox` / `--icebox-only` convention
- [ ] All existing tests pass (`make test`)
- [ ] Linting passes (`make lint`)

## Constraints

- Delivered output must use `todos/delivered.yaml` as the data source
- Python-level `cwd` parameters on internal functions are untouched — only CLI parsing is removed

## Risks

- `watch.py` and `next_machine/core.py` shell out to `telec` with `--project-root`. If flag removal lands without fixing these callers, those subprocess calls break. Implementation plan sequences these together in Task 2.5.
