# Requirements: integrate-session-lifecycle-into-next-work

## Goal

Integrate the session lifecycle principle into next-work orchestration so that:

- Review friction is resolved through direct peer conversation instead of context-destroying worker churn.
- Artifact verification is mechanical (CLI gate), not an AI reasoning task.
- The orchestrator explicitly follows session lifecycle discipline: dispatch, wait, read verdict, manage sessions, next phase.

## In Scope

### R1: Direct Peer Conversation for Review Friction

When review returns REQUEST CHANGES:

1. The orchestrator **keeps the reviewer session alive** (does not end it).
2. The orchestrator dispatches a fixer worker session.
3. The orchestrator instructs both to establish a `--direct` peer link (`telec sessions send <peer_session_id> --direct`) — one-time, idempotent.
4. The fixer and reviewer iterate together: fixer addresses findings, reviewer re-checks. Both have full context (reviewer has assessment, fixer has implementation).
5. The orchestrator monitors via heartbeat without participating in the conversation.
6. When the reviewer reports APPROVE (or the pair signals convergence), the orchestrator reads the final verdict from artifacts, ends both sessions, and continues the state machine.
7. If the pair cannot converge (max iterations or stalemate), the orchestrator applies the existing review-round-limit closure path.

Constraints for R1:

- Only one `--direct` send per pair (idempotent link establishment).
- Workers do not self-terminate — orchestrator always ends children.
- The reviewer session must remain tailable throughout the peer conversation.
- The fixer dispatched here replaces the current `next-fix-review` dispatch path when a reviewer session is still alive.

### R2: Automated Artifact Verification Gate

A new CLI command `telec todo verify-artifacts <slug> --phase <phase>` that mechanically checks:

- **Build phase**: Implementation plan tasks all checked `[x]`, committed changes exist on the worktree branch, `quality-checklist.md` Build Gates section populated.
- **Review phase**: `review-findings.md` exists and is non-placeholder, verdict present, `quality-checklist.md` Review Gates section populated.
- **General (all phases)**: `state.yaml` fields consistent with the claimed phase status.

The command:

- Exits 0 on pass, non-zero on failure.
- Outputs a structured report listing which checks passed and which failed.
- Is integrated into `next_work()` — called automatically before the orchestrator processes worker results (before `POST_COMPLETION` steps execute).
- Does not replace functional gates (`make test`, `demo validate`) — it complements them with artifact presence and consistency checks.

### R3: Session Lifecycle Principle in next-work

- Add `general/principle/session-lifecycle` to the `next-work` command's required reads.
- The `POST_COMPLETION` instructions in `core.py` explicitly follow session lifecycle discipline:
  - Orchestrator always ends children.
  - Signal sessions persist only for non-recoverable errors requiring human attention.
  - Artifact delivery is verified before ending sessions.
- The orchestrator's cleanup order: end children, then continue loop (orchestrator does not end itself — it's the persistent loop).

## Out of Scope

- Self-terminating workers (orchestrator always ends children — no change).
- Reading from dead/closed sessions.
- Changes to the prepare phase or DOR assessment.
- Changes to the finalize phase session management (already follows lifecycle).
- New adapter integrations.
- Changes to `telec sessions` CLI surface itself.

## Success Criteria

- [ ] When review returns REQUEST CHANGES, the reviewer session remains alive and a fixer establishes `--direct` peer link for iterative resolution.
- [ ] `telec todo verify-artifacts <slug> --phase build` exits 0 for a properly completed build, non-zero for missing/placeholder artifacts.
- [ ] `telec todo verify-artifacts <slug> --phase review` exits 0 for a properly completed review, non-zero for missing findings.
- [ ] Artifact verification runs automatically as part of `next_work()` before the orchestrator processes worker results.
- [ ] `agents/commands/next-work.md` includes `general/principle/session-lifecycle` in required reads.
- [ ] POST_COMPLETION instructions follow session lifecycle discipline (explicit end-children pattern, artifact verification before cleanup).
- [ ] Tests exist for `verify_artifacts()` covering pass and fail cases for build and review phases.
- [ ] Existing `max_review_rounds` limit still applies as a safety cap on peer conversation iterations.

## Constraints

- The state machine (`next_work()`) must remain stateless — it reads files and returns instructions. Session IDs for active peers must be managed by the orchestrator via POST_COMPLETION instructions, not stored in `state.yaml`.
- Backward compatibility: the existing fix-review dispatch path should remain available as a fallback when no reviewer session is alive (e.g., if the reviewer session died or was manually ended).
- The `verify-artifacts` command must be synchronous and fast (no network calls, no AI reasoning).

## Risks

- **Peer conversation stalemate**: Two agents iterating without converging wastes tokens. Mitigation: the existing `max_review_rounds` counter caps iterations, and the orchestrator applies pragmatic closure.
- **Reviewer session death during peer conversation**: If the reviewer session crashes mid-conversation, the fixer loses its peer. Mitigation: orchestrator heartbeat detects the dead session and falls back to the standard fix-review → re-review cycle.
- **Artifact verification false positives**: Placeholder detection (e.g., checking `review-findings.md` is non-template) requires heuristics. Mitigation: keep heuristics simple — check for the template markers from scaffolding.
