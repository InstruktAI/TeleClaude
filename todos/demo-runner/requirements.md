# Requirements: demo-runner

## Goal

Transform demos from post-finalize AI-composed narratives into build-phase deliverables that show working software. The demo is a celebration — a feast for anyone interested in what was built. It ships as a tested artifact alongside the code, discoverable and runnable through a conversational AI interface or CLI.

## In Scope

1. **Demo as build deliverable**: The builder creates a runnable demo during the build phase. The reviewer verifies it works. `snapshot.json` gains a `demo` field (shell command string) that specifies how to run the demonstration.
2. **Slug-based demo folders**: Demos live at `demos/{slug}/`, not numbered. Existing numbered folders migrate to slug-only names.
3. **Demo runner CLI**: `telec todo demo [slug]` — lists available demos or runs one by slug, with semver gating.
4. **`/next-demo` as the ceremony host**:
   - No slug: AI becomes the demo host — lists available demos, asks which one to present.
   - With slug: AI presents that demo — runs it via `telec todo demo <slug>` and celebrates the delivery with snapshot data (metrics, narrative acts) via `render_widget`.
   - This is purely the presentation ceremony. Builder guidance for creating demos belongs in the build procedure, not in `/next-demo`.
5. **Build gate**: Quality checklist template gains a "Demo is runnable and verified" checkbox in Build Gates.
6. **Decouple demo from finalize**: Remove demo dispatch step (step 3 "DEMO") from `POST_COMPLETION["next-finalize"]` in `core.py`. Demo is already done during build.
7. **Remove `demo.sh`**: Replaced by the `demo` field in `snapshot.json` + `telec todo demo` runner. Delete `demo.sh` from existing demo folders.
8. **Update demo artifact spec**: Update `docs/project/spec/demo-artifact.md` to reflect slug-based folders, `demo` field, and removal of `demo.sh` and `sequence`.
9. **Update demo procedure doc**: Update `docs/global/software-development/procedure/lifecycle/demo.md` to reflect build-phase creation, runner-based presentation, and removal of post-finalize orchestration.
10. **Builder guidance in build procedure**: The demo procedure doc must include guidance for builders on how to create demos (add `demo` field to `snapshot.json` with a shell command that demonstrates the feature).

## Out of Scope

- Retroactive demo generation for past deliveries without `demo` field.
- Structured/complex demo field format (stay with simple shell command string for now).
- Interactive TUI demo wizard.
- Demo recording or video capture.
- Normalizing existing `snapshot.json` field name inconsistencies — the runner reads actual field names as-is (see Constraints).

## Success Criteria

- [ ] `snapshot.json` schema includes optional `demo` field (string).
- [ ] Demo folders use slug-based naming: `demos/{slug}/`.
- [ ] Existing demos migrated from `demos/NNN-{slug}/` to `demos/{slug}/`.
- [ ] `sequence` field removed from migrated snapshots.
- [ ] `telec todo demo` (no slug) lists all available demos with title, slug, version, and delivered date.
- [ ] `telec todo demo <slug>` finds `demos/{slug}/snapshot.json`, reads the `demo` field, executes it.
- [ ] Semver gate: runner skips demos from incompatible major versions with a clear message.
- [ ] Runner handles missing `demo` field gracefully (warn + skip execution, exit 0).
- [ ] Runner handles nonexistent slug gracefully (error message, exit 1).
- [ ] Runner handles empty `demos/` directory gracefully.
- [ ] Quality checklist template includes "Demo is runnable and verified" in Build Gates.
- [ ] `/next-demo` (no slug) lists available demos and asks which one to present.
- [ ] `/next-demo <slug>` presents the demo — runs it via CLI and renders a celebration widget with snapshot data.
- [ ] `POST_COMPLETION["next-finalize"]` no longer dispatches `/next-demo`.
- [ ] `POST_COMPLETION["next-demo"]` entry removed (no longer needed as a post-completion step).
- [ ] `demo.sh` files removed from existing demo folders.
- [ ] Demo artifact spec updated (slug folders, `demo` field, no `demo.sh`, no `sequence`).
- [ ] Demo procedure doc updated (build-phase creation, builder guidance, runner-based presentation).
- [ ] All tests pass (`make test`) and lint passes (`make lint`).

## Constraints

- Backward compatibility: runner must handle demos without `demo` field (warn, don't crash).
- The `demo` field is a plain shell command string, executed with `shell=True` from the demo folder as cwd.
- Existing `snapshot.json` files use non-standard field names (`delivered_date` instead of `delivered`, `merge_commit` instead of `commit`, `insertions`/`deletions` instead of `lines_added`/`lines_removed`, `next` instead of `whats_next`). The runner reads actual field names with fallbacks. Schema normalization is out of scope.
- The delivery log is `todos/delivered.yaml` (not `delivered.md`). References in spec/procedure docs must use the correct filename.

## Risks

- Existing tests in `test_next_machine_demo.py` validate current POST_COMPLETION wiring, demo.sh behavior, and snapshot schema with spec-standard field names (e.g., `delivered`, `commit`). Tests must be updated in lockstep with implementation changes. The test fixtures use spec-standard names; existing demo files use non-standard names — tests should validate against what the runner actually reads.
- The `/next-demo` command rewrite changes agent workflow. Builders will need to create demos during build — this is a workflow shift that needs documentation in the build procedure.
- Removing the `POST_COMPLETION["next-demo"]` entry is safe — its only consumer is the finalize step, which is also being changed.
