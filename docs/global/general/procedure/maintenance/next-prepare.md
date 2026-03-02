---
id: 'general/procedure/maintenance/next-prepare'
type: 'procedure'
scope: 'global'
description: 'Orchestration procedure for next-prepare. Routes work to discovery, draft, or gate with strict phase separation and session lifecycle management.'
---

# Next Prepare Maintenance — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/maintenance/next-prepare-discovery.md
@~/.teleclaude/docs/general/procedure/maintenance/next-prepare-draft.md
@~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md
@~/.teleclaude/docs/general/concept/agent-characteristics.md

## Goal

Route todo preparation through the appropriate artifact-creation phase, supervise the
gate outcome, and clean up all sessions when the todo artifacts contain the final verdict.

1. **Discovery** or **draft** phase for artifact creation (router chooses one, never both).
2. Gate phase for formal DOR validation (runs in a separate worker session).
3. Supervise-and-conclude phase: read verdict, iterate if needed, clean up.

Discovery and draft produce the same output contract. Discovery uses two agents with
complementary profiles researching in parallel and converging. Draft uses a single agent.
The router selects based on input signal strength.

The router is responsible for the full lifecycle — including ending worker sessions
and itself when done.

## Preconditions

1. `todos/roadmap.yaml` exists.
2. Target slug is active (not icebox, not delivered) when slug is provided.
3. Worker command selected is explicit: `next-prepare-draft`, `next-prepare-gate`,
   or discovery runs inline in the router per the discovery procedure.

## Steps

### Routing

1. Inspect slug state and assess input signal strength:
   - Read `input.md`, `requirements.md`, `implementation-plan.md` if they exist.
   - Assess whether existing content is substantive (grounded in codebase and domain
     knowledge) or thin (scaffold templates, one-liner descriptions, vague intent).
2. **If input is thin** — route to discovery (inline). Thin means: `input.md` is empty
   or contains only scaffold comments, requirements are absent or skeletal, the roadmap
   description is the only signal. The router follows the Next Prepare Discovery procedure:
   it spawns a complementary agent, both research in parallel, converge, and produce artifacts.
3. **If input is substantive** — route to draft (inline). Substantive means: `input.md`
   contains a real brain dump with intent, requirements exist with concrete success criteria,
   or the implementation plan is already sketched. Run `/next-prepare-draft` inline.
4. If artifacts already exist and need formal DOR validation, dispatch gate directly (step 6).
5. Enforce session isolation: never reuse the same worker session for multiple phases.

### Supervision

6. Dispatch gate to a NEW worker session. Record the gate session ID.
7. After dispatching gate, set a heartbeat and wait for the gate worker notification.
8. On notification: read `state.yaml` to determine the gate verdict.
9. **Verify artifact delivery**: the gate worker commits its own artifacts. The router
   verifies the commit exists (`git log` on the todo folder). The commit is the proof
   of delivery — not the file state on disk. If the commit is missing, the router opens
   a direct conversation with the gate worker to resolve. Only the gate worker can
   produce its own assessment; the router never reconstructs gate output.
10. Only gate outcomes can authorize readiness transition criteria.

### Verdict handling

11. **Pass** (`dor.score >= 8`): proceed to cleanup.
12. **Needs work** (`dor.status == needs_work`): open a direct conversation with the
    gate worker per the Agent Direct Conversation procedure. The router has codebase
    context from running discovery or draft; the gate worker has the DOR assessment.
    Together they iterate on the artifacts until quality lands. Gate worker updates
    artifacts. Router re-reads `state.yaml` after each iteration. When pass: proceed
    to cleanup.
13. **Needs decision** (`dor.status == needs_decision`): blockers require human input.
    Proceed to cleanup. The blockers in `dor-report.md` are the signal for the human.

### Cleanup

14. **Pass / needs_work resolved**: End the gate worker session (`telec sessions end <gate_session_id>`).
    The todo folder is the durable evidence trail. Do NOT stay alive to report results —
    the commit is the report. Then end yourself:
    ```bash
    telec sessions end "$(cat "$TMPDIR/teleclaude_session_id")"
    ```
15. **Needs decision**: Do NOT end the gate session — it stays alive as a visible signal
    to the human. The blockers in `dor-report.md` are the signal. End yourself:
    ```bash
    telec sessions end "$(cat "$TMPDIR/teleclaude_session_id")"
    ```
16. The todo folder (`todos/<slug>/`) is the durable evidence trail for all outcomes.
    The gate session persists only when human attention is required.
    The router session never persists — ending yourself is always the final action.

## Outputs

1. Clear phase routing decision (discovery or draft).
2. Preparation artifacts from discovery or draft phase.
3. Final DOR verdict from gate phase (written to todo artifacts).
4. On pass: all sessions ended. On needs_decision: gate stays alive as signal.

### DOR contract

Per processed slug, both phases may update:

- `requirements.md`
- `implementation-plan.md`
- `dor-report.md`
- `state.yaml` (`dor` section)

`state.yaml.dor` schema:

```json
{
  "dor": {
    "last_assessed_at": "2026-02-09T17:00:00Z",
    "score": 8,
    "status": "pass",
    "schema_version": 1,
    "blockers": [],
    "actions_taken": {
      "requirements_updated": true,
      "implementation_plan_updated": true
    }
  }
}
```

Allowed values:

- `dor.score`: integer `1..10`
- `dor.status`: `pass`, `needs_work`, `needs_decision`

Threshold constants:

- Target quality: `8`
- Decision required: `< 7`

## Recovery

1. If phase routing is ambiguous, default to discovery (the heavier path catches what
   the lighter path would miss; the reverse is not true).
2. If gate lacks required draft artifacts, stop and return `needs_work` with missing files listed.
3. If gate session ends without notification (flaky delivery), tail it once and proceed
   with verdict reading.
4. If direct conversation stalls (heartbeat fires with no progress after two iterations),
   write blockers to `dor-report.md` and proceed to cleanup.
