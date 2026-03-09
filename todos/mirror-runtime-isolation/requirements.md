# Requirements: mirror-runtime-isolation

## Goal

- Remove mirror-induced API hang risk by isolating reconciliation runtime and enforcing strict mirror correctness invariants (canonical corpus membership, exact identity, and convergent reconciliation behavior).

## Scope

### Lane A: Containment (must land first)

- Convert transcript discovery for mirror/historical reconciliation to a positive allowlist contract (not exclusion filters).
- Restrict reconciliation and mirror-backed search inputs to canonical transcripts only.
- Move reconciliation out of the daemon event loop into a separate worker/process.
- Add a post-prune measurement gate before closing containment:
  - reconciliation processed count per run
  - main DB WAL growth during reconciliation
  - API latency for `/sessions`, `/health`, `/computers`
  - API loop-lag warnings while reconciliation is active
- Apply conditional DB split gate using measured write pressure:
  - if post-prune writes stay high, move mirror/search storage to a separate DB in this lane
  - if post-prune writes collapse, DB split can be deferred to Lane B

### Lane B: Correctness (after containment gate)

- Replace fallback mirror identity behavior with exact canonical source identity.
- Persist durable skip/tombstone state for empty transcripts so they are not reprocessed forever.
- Run canonical-only backfill after identity model is stable.

## Canonical Transcript Contract (Hot Corpus)

- Claude canonical:
  - Root: `~/.claude/projects/`
  - Shape: `<project-dir>/<session-id>.jsonl`
  - Explicitly non-canonical: any path under `/subagents/`
- Codex canonical:
  - Root: `~/.codex/sessions/`
  - Shape: `YYYY/MM/DD/rollout-*-<native_session_id>.jsonl`
  - Explicitly non-canonical: `~/.codex/.history/sessions/**`
- Gemini canonical:
  - Root: `~/.gemini/tmp/`
  - Shape: `**/chats/session-*.json`

## Out of Scope

- Search UX/product redesign.
- Reintroducing non-canonical artifacts into the hot corpus.
- Bundling `/todos/integrate` migration implementation into mirror code changes.

## Success Criteria / Proof Obligations

- [ ] Discovery invariant: only allowlisted canonical transcript shapes are eligible for mirror processing.
- [ ] Identity invariant: mirror primary key is canonical source identity; fallback `session_id` semantics are removed.
- [ ] Runtime isolation invariant: API loop-lag warnings do not appear while reconciliation runs.
- [ ] Convergence invariant: processed reconciliation count trends toward near-zero steady state after initial prune/backfill.
- [ ] Empty-transcript invariant: once classified as empty, transcripts remain skipped until source content changes.
- [ ] Storage decision invariant: DB split is decided from measured post-prune write pressure, not preference.
- [ ] Workflow boundary invariant: `/todos/integrate` receipt-backing is tracked as a separate dependent todo.

## Constraints

- Preserve canonical transcript rendering semantics unless a requirement explicitly changes behavior.
- Keep containment and correctness incrementally mergeable, each with rollback boundaries.
- Do not depend on non-canonical corpus inputs for steady-state metrics.

## Risks

- Ambiguous canonical contract will reintroduce heuristic discovery drift.
- Process isolation alone can shift failure mode if write pressure remains high.
- Delaying DB split despite high write pressure can preserve contention-induced instability.
