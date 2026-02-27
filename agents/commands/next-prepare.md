---
argument-hint: '[slug]'
description: Prepare router command - draft, dispatch gate, supervise, cleanup
---

# Prepare

You are now the Prepare router.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md

## Purpose

Run draft inline, dispatch gate to a worker, supervise the outcome, and clean up sessions.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Updated todo artifacts (requirements, implementation plan, demo, DOR report).
- Gate verdict written to `state.yaml`.
- On pass/needs_work resolved: both sessions ended. The todo folder is the evidence.
- On needs_decision: gate session stays alive as a signal to the human. Router ends itself.

## Steps

1. Inspect todo state.
2. If artifacts are missing or weak, run `/next-prepare-draft` inline, then continue to step 4.
3. If upon startup artifacts exist and need formal DOR validation, dispatch gate (step 4) directly.
4. Dispatch gate to a NEW worker session. Record the gate session ID.
   Use EXACTLY: `telec sessions run --command /next-prepare-gate --args "<slug>" --project <project_path>`
5. Set a heartbeat: `echo "Note To Self: check gate worker status for <slug>" && sleep 300`
6. Wait. The gate worker will notify you automatically when its turn completes.
7. On notification (or heartbeat with no notification): verify the gate worker committed its artifacts (`git log --oneline -1 -- todos/<slug>/`). The commit is the proof of delivery. Read `todos/<slug>/state.yaml` from the committed state to get the DOR verdict. If the commit is missing, open a direct conversation with the gate worker to resolve — only the gate worker can produce its own assessment.
8. **If `dor.status == pass` (score >= 8)**: end the gate session (`telec sessions end <gate_session_id>`), then end your own session (`telec sessions end <own_session_id>`).
9. **If `dor.status == needs_work`**: open a direct conversation with the gate worker (`telec sessions send <gate_session_id> --direct`). Collaborate to resolve quality gaps — you have codebase context from running draft, the gate worker has the DOR assessment. Gate worker updates artifacts as you iterate. When `state.yaml` shows pass: end gate session, then end own session.
10. **If `dor.status == needs_decision`**: the todo has blockers requiring human input. Do NOT end the gate session — it stays alive as a visible signal. End your own session only.

Heartbeat discipline: reset the heartbeat after each check if the gate worker is still running. If the gate session ended but no notification arrived (flaky delivery), tail it once (`telec sessions tail <gate_session_id>`) and proceed with step 7. During direct conversation (step 9), maintain an anchor Note To Self per the direct conversation procedure.
