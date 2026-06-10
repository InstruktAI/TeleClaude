## Build Gates (Builder)

- [x] Task 1: Resolve a target-owned companion before reading the selected body
- [x] Task 2: Align `telec docs get --target` help text with the real contract
- [x] Task 3: Add phase-2 companion retrieval regression coverage

### Verification

- `uv run pytest tests/context/test_doc_snippet_three_phase_retrieval.py::test_phase2_target_uses_matching_companion_replacement_body`: FAIL before accepting the post-fix snapshot; diff changed `# Live Parent` to `# Companion`.
- `uv run pytest tests/context/test_doc_snippet_three_phase_retrieval.py --snapshot-update`: PASS (`5 passed`, `5 snapshots passed/generated/updated`).
- `telec code test`: PASS (`5 passed`, `5 snapshots passed`).
- `telec code lint`: PASS.

### User-Facing Verification

- Path: `telec docs get <id> --target <slug>` exercised through `build_context_output(..., target_slug="fix-docs-get-target-companion-bodies")` in `tests/context/test_doc_snippet_three_phase_retrieval.py`.
- Observed result: the selected phase-2 snippet body renders the target-owned companion replacement body while plain reads and non-owning targets keep the live parent body; inline planned sections still resolve for the owning target.
- CLI surface source verification: `uv run python` read `CLI_SURFACE["docs"].subcommands["get"]` and confirmed the `--target` description includes planned sections and companion replacement bodies. The installed `telec docs get --help` remained stale in this worktree until the command surface is regenerated/deployed.
