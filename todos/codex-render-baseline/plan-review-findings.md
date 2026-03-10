# Plan Review Findings: codex-render-baseline

Critical:
- ~~Scope split required.~~ **OVERRIDDEN by architect.** The split finding is incorrect:
  (1) Total scope is ~400 lines including tests — well within one builder session.
  (2) R4-R5 are the regression guard FOR R1-R3 — the fixtures prove the corrections
  don't break parser semantics. Shipping corrections without the guard defeats purpose.
  (3) Requirements are exhaustively detailed (exact files, lines, signatures) — this is
  mechanical execution, not discovery. Detail inverts complexity per DOR heuristics.
  (4) Coordination cost of splitting exceeds the session-size benefit for this amount of work.

Important:
- None.

Suggestion:
- None.

Resolved during review:
- Tightened the R3 `is_pane_dead()` cadence verification so the test proves a 5-iteration throttle instead of allowing weaker call counts.
- Corrected the fixture corpus specification so every planned snapshot includes ANSI escapes, matching the stated parser-fixture requirement.
- Added explicit `demo.md` coverage and grounding metadata so the plan anticipates the mandatory demo review lane.
