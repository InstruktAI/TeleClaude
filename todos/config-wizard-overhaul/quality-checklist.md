# Quality Checklist: config-wizard-overhaul

- [x] Root cause identified and documented in bug.md
- [x] Fix is minimal and scoped to the four identified issues
- [x] No unrelated changes introduced
- [x] `_normal_style()` reads theme at render time (not import time)
- [x] `config_guided` parameter wired end-to-end: CLI → `_run_tui` → `TelecApp` → `on_mount`
- [x] `_appearance_refresh` refreshes `ConfigContent` alongside other widgets
- [x] Tests pass (pre-commit hooks)
- [x] Lint passes (pre-existing unrelated failure in animations/general.py excluded)
- [x] Commit is atomic — single commit covers all four related fixes

## Build Gates

- [x] Tests pass
- [x] Lint passes
- [x] All implementation-plan tasks completed
- [x] bug.md documents root cause and fix
- [x] No debug or temporary code committed
