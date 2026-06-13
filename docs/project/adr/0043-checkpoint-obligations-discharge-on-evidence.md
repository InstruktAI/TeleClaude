---
date: '2026-06-12'
description: 'Committed code is sourced into the checkpoint action ledger as derived maintenance obligations, each discharged when its evidence is observed in any later checkpoint cycle; the wholesale user-prompt-submit clear is a backstop, not the only clear.'
number: '43'
supersedes:
  - project/adr/0037-checkpoint-ledger-separates-commit-detection
visibility: 'public'
---

# Checkpoint Obligations Discharge On Evidence — ADR

## Context

ADR-0037 separated commit detection from the time-anchored action ledger so a
commit would not empty the ledger and silently drop implied maintenance (the
daemon-code-committed-but-not-restarted failure). Its mechanism recorded the
committed **file list** into a session-scoped marker and unioned that payload into
the turn's effective files on every checkpoint cycle, hard-clearing the marker only
at `user_prompt_submit`.

That mechanism coupled a persistent action source to an ephemeral evidence window.
The committed files were re-injected and re-categorized into the same obligation
(e.g. "run `telec sync`") on every cycle, but suppression evidence is scoped to a
single checkpoint cycle (the tool calls since the last checkpoint anchor). The
agent performs the maintenance command in _response_ to checkpoint N, which lands
in cycle N+1, while cycle N+1 still re-asserts the obligation from the unchanged
marker. In any cycle where the satisfying command is not inside that cycle's
window, the obligation re-fires — an unbounded checkpoint loop that ends only when a
real user prompt wholesale-clears the marker. Observed live: a turn committed a doc
snippet and ran `telec sync`, then three consecutive zero-change `agent_stop`
cycles each re-emitted the same `telec sync` obligation.

ADR-0037 accepted this as a consequence — it framed recurring cross-turn
checkpoints as a feature that surfaces over-tight heuristics to the human. That
framing is wrong: recurrence is legitimate only when the action was **not**
performed. Once performed, persistence with no discharge is the agent being
hammered for work it already did.

The deeper error is the abstraction. The marker stored **files** and re-derived
**actions** from them every cycle. Files are a proxy; what is actually owed after a
commit is a fixed set of maintenance actions, derivable once at commit time.

## Decision

Source committed code into the action ledger as an **obligation ledger** rather
than a file list.

- At sealed `telec code commit`, categorize the committed pathspec once and record
  the owed `main_only` maintenance actions (make install / uv sync / make restart /
  telec sync) into a session-scoped obligation ledger — the owed actions, not the
  raw file list.
- The engine unions the outstanding obligations into the turn's effective actions,
  so commit-implied maintenance survives the HEAD move for any session.
- Each obligation is discharged the moment its evidence is observed in any
  checkpoint cycle — the cycle that surfaced it or a later one — and a discharge is
  durable, so a satisfied obligation cannot re-fire in a subsequent cycle.
- Test and log-check actions are not recorded as commit obligations; they stay
  cycle-local advisories on the dirty tree, since their soft detectors cannot
  reliably discharge and would otherwise loop.
- `user_prompt_submit` remains the wholesale clear, as a turn-boundary backstop
  only.

This generalizes the integrator post-merge maintenance-sourcing precedent to any
sealed commit. Git is consulted only as the category oracle, never as the arbiter
of what is in-scope or done.

The governing invariant: every action the checkpoint emits has a reliable detector
and is discharged the moment that detector fires; nothing the agent was told to do
can re-fire once it has been observed done.

## Consequences

- A turn that commits maintenance-bearing code surfaces the implied actions, and
  each disappears permanently once its evidence is observed — in the same cycle or
  any later one. The zero-change re-fire loop is structurally impossible.
- The action source and the evidence window now share a lifetime: an obligation
  lives exactly until it is satisfied or the turn resets. Recurrence now means what
  it should — the action was not performed.
- Cross-HEAD persistence is deliberately narrowed to the `main_only` maintenance
  subset; tests and log-check for committed code are advisory and do not survive the
  commit, removing the soft-detector loop risk their weaker evidence created.
- The obligation set is a smaller, more honest surface than a re-categorized file
  list: it carries exactly the outstanding work, not a proxy re-interpreted every
  cycle.

## Alternatives Considered

- **Keep the file marker, add a per-file discharge flag.** Rejected: a committed
  file maps to multiple categories, so "is this file still owed" couples to "are all
  its categories evidenced" — the same re-categorization indirection the obligation
  model removes.
- **Derive committed-this-turn files from `git diff turn_anchor..HEAD` each cycle.**
  Rejected: git-derived obligations still need discharge-state tracking, so a ledger
  is required regardless of the source; the discharge state is the real thing to
  persist.
- **Clear the marker at the end of the cycle that records it (single-shot).**
  Rejected: a single-shot marker loses the obligation if the agent does not act in
  that one cycle, reintroducing ADR-0037's original dropped-maintenance failure.
