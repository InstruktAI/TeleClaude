# Demo: lifecycle-enforcement-gates

## Validation

<!-- Prove the subcommand split works -->
<!-- Run `telec todo demo validate` on a demo.md with bash blocks — should exit 0 -->
<!-- Run `telec todo demo validate` on the scaffold template (no blocks) — should exit 1 -->
<!-- Run `telec todo demo validate` on a demo.md with `<!-- no-demo: reason -->` — should exit 0, log reason -->
<!-- Run `telec todo demo run` on a demo.md with a simple passing block — should exit 0 -->
<!-- Run `telec todo demo run` on the scaffold template — should exit 1 (the silent-pass fix) -->
<!-- Run `telec todo demo create` on a prepared demo.md — should promote to demos/ and create minimal snapshot.json -->
<!-- Run `telec todo demo` (no args) — listing should still work -->

<!-- Prove the state machine gates work -->
<!-- Set up a worktree with a slug that has build=complete but a failing demo (scaffold template) -->
<!-- Call next_work — should reset build to started and return gate-failure instructions -->
<!-- Set up a worktree with a slug that has build=complete and a passing demo + passing tests -->
<!-- Call next_work — should proceed to review dispatch -->

<!-- Prove lazy state marking works -->
<!-- Call next_work for a pending item — verify state.yaml is NOT mutated, output contains marking instructions -->

## Guided Presentation

<!-- Walk through the defense-in-depth model: -->
<!-- 1. Show a builder running their own gates (validate + run) — self-discipline layer -->
<!-- 2. Show the state machine catching a builder who didn't fill in demo.md — enforcement layer -->
<!-- 3. Show POST_COMPLETION flow: builder session stays alive until gates pass -->
<!-- 4. Show snapshot.json reduction — minimal metadata, narrative from source artifacts -->
<!-- 5. Show the end-to-end flow: build -> gates pass/fail -> review dispatch -->
