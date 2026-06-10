## Build Gates (Builder)

- [x] Task 1: Remove `UNKINDED` and `KIND_PROPOSED` from the Python lifecycle enum.
- [x] Task 2: Make `kind=None` imply no `lifecycle_phase` in the todo state model.
- [x] Task 3: Collapse kind proposal/approval stamps into `--kind-assign`.
- [x] Task 4: Remove `kind_proposal` from stamp payload normalization.
- [x] Task 5: Replace CLI stamp flags with `--kind-assign`.
- [x] Task 6: Create kind-less todos with `kind=None` and route them on missing kind.
- [x] Task 7: Preserve kind-less no-phase state during on-read upcycle.
- [x] Task 8: Show kind-less todos as `classify` and bucket `diagnose` as prepare.
- [x] Task 9: Project and render kind-less rows as `K:unknown` / `P:classify`.
- [x] Task 10: Update `/analyze-todo-input` command to autonomous assignment.
- [x] Task 11: Amend ADR companion for autonomous classification.
- [x] Task 12: Update state-stamping spec companion for `--kind-assign`.
- [x] Task 13: Update workflow domain spec companion for no pre-kind phases.
- [x] Task 14: Update telec CLI surface companion for `--kind-assign`.
- [x] Task 15: Update todo-creation spec companion for kind-less no-phase intake.
- [x] Task 16: Remove dead Rust v2 pre-kind phase variants.
- [x] Task 17: Update stale TUI markup-escape fixture key.

### Verification

- `telec code test`: PASS (`28 passed`, `13 snapshots passed`; Rust workflow lib `69 passed`)
- `telec code lint`: PASS
- `cargo build --workspace`: PASS
- `cargo test --workspace --lib --quiet`: PASS (`192 passed`)
- `cargo test -p workflow --lib --quiet`: PASS (`69 passed`)
- `cargo clippy --workspace --all-targets -- -D warnings`: PASS
- `cargo test --workspace`: BLOCKED by existing environment requirement (`identity` migration tests require `DATABASE_URL`)
- `telec sync`: PASS
- `rg -n "UNKINDED|KIND_PROPOSED|kind_proposed|--kind-proposed|--kind-approved|KindProposalState|kind_proposal|_PRE_KIND|unkinded" teleclaude agents/commands/analyze-todo-input.md crates/workflow/src`: PASS (no matches)

### User-Facing Verification

- Kind-less create persists `kind=None` without `lifecycle_phase`, emits `lifecycle_phase=null`, and dispatches `/analyze-todo-input`.
- `telec todo stamp <slug> --kind-assign change` assigns the kind and entry phase in one write; reassigning an already-kinded todo is refused.
- `telec todo stamp <slug> --kind-assign task "<content>"` writes a `task-plan` and lands the todo at `prepared`.
- `telec todo show` reports a kind-less row as `stage=prepare`, `current.phase=classify`; `diagnose` also buckets as prepare.
- Roadmap/TUI projection renders kind-less rows as `K:unknown` and `P:classify`, and manual prepare selection skips them until classification.
