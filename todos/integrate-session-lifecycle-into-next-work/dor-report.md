# DOR Report: integrate-session-lifecycle-into-next-work

## Draft Assessment

**Assessed at:** 2026-02-28
**Phase:** Draft (pre-gate)

### Gate 1: Intent & Success

**Status:** PASS

The problem statement is explicit: next-work orchestration lacks session lifecycle discipline, causing context-destroying worker churn during review friction and relying on AI for repetitive artifact verification.

Three clear outcomes:

1. Direct peer conversation replaces fix-review dispatch churn
2. Mechanical CLI gate replaces AI artifact checking
3. Session lifecycle principle wired into orchestrator's required context

Success criteria are concrete and testable (CLI exit codes, observable session behavior, grep-verifiable documentation changes).

### Gate 2: Scope & Size

**Status:** PASS (with note)

The work is broken into three independent workstreams:

1. Artifact verification gate (new function + CLI + integration)
2. Direct peer conversation (POST_COMPLETION modification + command update)
3. Session lifecycle wiring (documentation change)

Each workstream is independently testable. The total scope is substantial but fits a single focused build session because the changes are concentrated in `core.py` with one new test file and minor documentation edits.

### Gate 3: Verification

**Status:** PASS

- Artifact verification: unit tests for pass/fail cases per phase
- Direct peer conversation: observable through session listing during a review cycle
- Session lifecycle wiring: grep-verifiable in command artifact
- Integration: existing `make test` suite covers state machine routing

### Gate 4: Approach Known

**Status:** PASS

All patterns exist in the codebase:

- `run_build_gates()` is the model for `verify_artifacts()`
- `POST_COMPLETION` dict already handles per-command orchestration logic
- `telec sessions send --direct` exists and is documented
- CLI command registration pattern is established in `telec.py` and `tool_commands.py`

### Gate 5: Research Complete

**Status:** N/A (no third-party dependencies)

### Gate 6: Dependencies & Preconditions

**Status:** PASS

No external dependencies. Required capabilities:

- `telec sessions send --direct` — already implemented
- `telec sessions run` — already implemented
- `telec sessions end` — already implemented
- State machine routing — existing infrastructure in `core.py`

### Gate 7: Integration Safety

**Status:** PASS

Changes are incremental:

- `verify_artifacts()` is additive — new function, doesn't modify existing behavior
- POST_COMPLETION changes are backward-compatible — APPROVE path unchanged, REQUEST CHANGES path adds peer conversation before the existing fallback
- Documentation change is non-breaking

### Gate 8: Tooling Impact

**Status:** PASS

New CLI subcommand `telec todo verify-artifacts` follows existing `todo` subcommand patterns. Command surface documentation will need updating but that's handled by `telec sync`.

## Open Questions

1. **Review round counting during peer conversation:** Should each back-and-forth between fixer and reviewer count as a "review round" for the `max_review_rounds` limit? The current assumption is yes — the existing counter tracks how many times review transitions through REQUEST CHANGES.

2. **Fallback trigger for standard fix-review:** When exactly should the orchestrator fall back to the standard fix-review dispatch instead of peer conversation? Current assumption: only when no reviewer session ID is available (e.g., reviewer session died or was manually ended before the orchestrator processed the verdict).

## Assumptions

- The orchestrator is capable of managing session IDs in its working memory (POST_COMPLETION instructions, not state.yaml) across the peer conversation sub-loop.
- `telec sessions send --direct` is idempotent — sending it twice to the same pair doesn't create duplicate links.
- Workers receiving `--direct` messages can process them alongside their primary task without disruption.
