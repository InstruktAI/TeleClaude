---
id: general/procedure/memory-extraction/overview
type: procedure
domain: general
scope: global
visibility: public
status: target
delivered_by: [v2-memory]
applies_to: v2
description: General playbook for memory extraction agents. Read a session mirror, dedup candidate observations against doc snippets, save survivors as triples. Append-only event-store semantics. Category-specific overrides live in thin-wrapper procedures.
---

# Memory Extraction — Procedure

## Required reads

- @docs/project/spec/domain/memory.md

## Goal

Turn a session's conversation into a stream of durable memory triples that survive the session and feed downstream pattern-matchers, without polluting the memory store with content already codified elsewhere or with interpretive synthesis.

## Preconditions

- The agent is the memory miner — the sole authorized writer to memory. No other agent role may run this procedure.
- The session being extracted has a corresponding mirror (`session_mirrors.text_content` populated). The mirror's `mirror_id` is the provenance handle the agent will record on every saved triple.
- The agent has loaded its category-specific feature spec (human or project) which declares the predicate vocabulary, subject resolution rules, and out-of-scope boundary.
- The agent has read access to existing doc snippets (`telec docs index` and `telec docs get`) — without this, the dedup discipline cannot be enforced.

## Steps

### Phase A — Collect candidates to scratchpad

1. Read the session mirror text content for this `mirror_id`.
2. Identify every candidate observation that falls in this agent's category scope. Write each candidate to a working scratchpad with: a tentative subject, a tentative predicate from the vocabulary, a tentative object. Do not save anything yet. Do not dedup yet. Just enumerate.
3. Discard candidates that are clearly out-of-scope per the category boundary (defer to the other memory miner, or discard entirely if neither category covers it).
4. Discard candidates that are interpretation, not demonstrated fact. "The human seems frustrated" is interpretation. "The human stated they were frustrated" is fact. Only demonstrated facts survive.
5. Discard behavioral patterns (sequences of actions, repeated tool calls) — those are not memory.

### Phase B — Per-candidate dedup-and-save

For each candidate that survived Phase A:

1. **Validate the predicate.** It must appear in the agent's category vocabulary. If it doesn't, either rewrite the candidate using an allowed predicate or discard.
2. **Search doc snippets** for substantive coverage of the candidate's content. Use `telec docs index` filtered to relevant areas/domains, then `telec docs get` for any snippet whose description matches. If the candidate is already codified there — even with different wording — **discard the candidate**. This is the mandatory dedup-against-docs discipline. Codified knowledge does not get re-encoded as memory.
3. **Save the survivor:**
   ```
   telec memories save --category <h|p> --subject <s> --predicate <p> --object <o> --source-mirror <mirror_id>
   ```
4. **Do not search memory for existing duplicates at write time.** The store is append-only; repeated observations are meaningful and signal salience to downstream consumers.

### Phase C — Advance the marker

The agent's high-water mark for this `(category, mirror_id)` is implicit in the `source_mirror_id` of saved rows plus, optionally, an explicit ack to the source cursor (`telec sessions ack`). The agent does not maintain its own marker state outside the memory store and the cursor system.

## Outputs

- Zero or more new memory rows, each with the agent's category, a vocabulary-valid predicate, a non-empty subject and object, and the source mirror's id as provenance.
- A brief summary of activity for the dispatcher (count of candidates collected, count discarded by reason, count saved).

## Pre-completion checklist

- Every saved row uses a predicate from the agent's category vocabulary.
- Every saved row carries the correct `source_mirror_id`.
- No row was saved for content already codified in doc snippets.
- No row was saved for interpretive synthesis (mood/intent guesses).
- No row was saved for behavioral patterns or tool-call sequences.
- No todos were created. No doc snippets were drafted. No other artifacts were produced.

## Report format

```
MEMORY EXTRACTION COMPLETE
Category: <human | project>
Mirror: <mirror_id>
Candidates collected: <n>
Discarded — out of scope: <n>
Discarded — interpretive: <n>
Discarded — codified in docs: <n>
Discarded — vocabulary mismatch: <n>
Saved: <n>
```

## Discipline

This procedure's single most-violated rule is the dedup-against-docs check in Phase B. Skipping it turns memory into a junk drawer next to the codified library: the same fact appears twice in two systems that drift over time, and downstream consumers can't tell which is authoritative. When in doubt about whether a candidate is "already covered" by docs, treat it as covered and discard. The cost of a missed memory is far lower than the cost of duplicate-noise pollution. The other anchor: this agent does NOT interpret, synthesize, claim patterns, or create artifacts beyond memory rows. Those are downstream concerns owned by other jobs that read accumulated memory — never this agent's job.

## Recovery

- Re-runs are safe. The store's append-only semantics mean a re-run produces no harm — duplicates are meaningful, not corruptive.
- If a row was saved that violated the procedure (interpretation, codified content, behavioral pattern), it can be removed via `telec memories delete <id>`. Operator-level cleanup; not part of normal flow.
- If the doc-snippet dedup was skipped on an earlier run, a later pass with the discipline applied will produce correct behavior for new content; the polluted historical rows require explicit cleanup.
