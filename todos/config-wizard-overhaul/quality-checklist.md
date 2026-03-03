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

## Review Gates (Reviewer)

- [x] All four bug fixes correct and verified against source
- [x] Paradigm-fit verified — no data-layer bypasses or copy-paste duplication
- [x] Tests for behavioral changes in telec.py (guided=True wiring, start_view=4)
- [x] demo.md with no-demo justification or minimal stub
- [x] No Critical findings
