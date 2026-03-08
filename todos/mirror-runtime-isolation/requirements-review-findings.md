# Requirements Review Findings: mirror-runtime-isolation

## Finding 1: Unmarked inferences from codebase knowledge

**Severity: Important**

Several requirements are inferred from codebase analysis rather than explicitly stated
in `input.md`, but none carry an `[inferred]` marker. The human cannot distinguish what
they said from what the system assumed.

Unmarked inferences:

1. **Canonical Transcript Contract paths and shapes** — `input.md` states "Hot corpus must
   be an allowlist by agent" and ".history and subagents are not part of mirror." The exact
   root paths (`~/.claude/projects/`, `~/.codex/sessions/`, `~/.gemini/tmp/`), glob shapes
   (`YYYY/MM/DD/rollout-*-<native_session_id>.jsonl`, `**/chats/session-*.json`), and
   exclusion predicates (`/subagents/`, `.history`) are inferred from `transcript_discovery.py`.

2. **Lane A/B sequencing** — `input.md` describes symptoms and decisions but does not
   structure the work into containment-first and correctness-after lanes. This phasing is
   an inferred architectural decision.

3. **Measurement gate metrics** — `input.md` says "control-plane responsiveness stays stable"
   and "DB isolation applied when measurement gate indicates." The specific metrics
   (reconciliation processed count per run, main DB WAL growth, API latency for specific
   endpoints, loop-lag warnings) are inferred from existing `monitoring_service.py`
   capabilities.

**Remediation:** Add `[inferred]` markers to each item derived from codebase analysis
rather than human-stated intent.

---

## Finding 2: Conditional DB split config surface unaddressed

**Severity: Suggestion**

Lane A's conditional DB split gate says "move mirror/search storage to a separate DB in
this lane" if post-prune writes stay high. If this path triggers, a new database path
config key is needed, `config.sample.yml` must be updated, and wizard exposure must be
confirmed. The requirements do not mention this config surface.

The DoD gate for configuration reads: "If the work introduces new configuration (config
keys, env vars, YAML sections), they are listed explicitly and their wizard exposure is
confirmed."

**Remediation:** Add a conditional config surface note: if DB split triggers, specify
the expected config key and confirm wizard/sample coverage.

---

## Finding 3: Storage decision invariant verification gap

**Severity: Suggestion**

The success criterion "Storage decision invariant: DB split is decided from measured
post-prune write pressure, not preference" is verifiable as a decision record but not
as a test. The requirements do not define what constitutes "high write pressure" in
concrete terms — no threshold, no duration window, no metric source.

A builder cannot prove this gate was applied correctly without concrete parameters.
A reviewer cannot verify the decision was evidence-based without knowing what evidence
was expected.

**Remediation:** Define the measurement protocol: which metric(s), what threshold(s),
and over what observation window the DB split decision is made. Even approximate values
(e.g., "WAL growth exceeding N KB during a reconciliation pass" or "loop-lag warnings
exceeding N occurrences per pass") would suffice.
