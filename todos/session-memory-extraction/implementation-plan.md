# Implementation Plan: session-memory-extraction

## Overview

Implement the existing `SessionMemoryExtractionJob` as one coherent pipeline in
`jobs/session_memory_extraction.py`: read a cleaned mirror-backed transcript
delta, extract personal memories, business memories, and actionable items
through the existing structured-output summarizer boundary, persist/publish
through the existing memory and channels boundaries, and remove the dead
`/compact` injection.

This remains a single builder-sized todo. The work is concentrated in one job
file plus its 1:1 unit test home. The mirror, transcript, memory, logging, and
channel modules are grounding references, not new workstreams.

## Atomicity Decision

**Atomic.** This is one behavior change: turn a stubbed extraction job into a
working extraction job. The required code lives primarily in
`jobs/session_memory_extraction.py`, with one new test file at
`tests/unit/test_session_memory_extraction.py`. Splitting this into
"delta-reading", "memory extraction", and "action publication" would create a
half-working pipeline and add coordination overhead without reducing session
size.

## Grounding Notes

- [inferred] The previous successful extraction boundary should come from
  `session.help_desk_processed_at`, not `session.last_memory_extraction_at`.
  Source grounding: `teleclaude/services/maintenance_service.py` already sets
  `last_memory_extraction_at` before the extraction job runs as an idle marker.
  Using that field as the read boundary would produce empty deltas for idle
  sessions. The plan therefore treats `help_desk_processed_at` as the durable
  "last successful extraction" marker while leaving maintenance-service timing
  unchanged.
- The build must reuse the existing `_call_summarizer` surface in
  `teleclaude/core/summarizer.py` exactly as-is. The current helper is a
  grounding dependency, not a planned edit.
- The build must reuse `MemoryStore.save_observation(...)` and
  `teleclaude.channels.publisher.publish(...)` rather than introducing new
  persistence or transport interfaces.
- The 1:1 unit-test home for this job is
  `tests/unit/test_session_memory_extraction.py`, matching the existing pattern
  used by other root-level `jobs/*.py` modules.

## Task 1: Activate the unit-spec home for the job

**What**

Create or complete `tests/unit/test_session_memory_extraction.py` as the single
unit-test home for `jobs/session_memory_extraction.py`, and place the expected-
failure specs for FR1-FR5 there so the builder can remove the relevant xfail
markers before each code change.

**Why**

The repo currently has no test home for this job. The testing and test-
structure policies require a 1:1 mapping and test-first execution. Establishing
the test file first gives the builder a stable contract for every behavior in
scope and keeps the work inside the repo's existing `tests/unit/test_*.py`
layout instead of inventing a new `tests/unit/jobs/` subtree.

**Referenced files**

- `tests/unit/test_session_memory_extraction.py`

**Verification**

The builder makes these spec tests GREEN as the code work lands:

- `test_read_transcript_delta_returns_none_without_mirror`
- `test_read_transcript_delta_returns_none_without_new_messages`
- `test_read_transcript_delta_returns_clean_conversation_lines`
- `test_process_session_returns_early_when_delta_is_empty`
- `test_process_session_uses_help_desk_processed_at_as_delta_boundary`
- `test_process_session_skips_personal_extraction_without_identity_key`
- `test_process_session_does_not_inject_compact`
- `test_run_async_continues_after_per_session_failure`

## Task 2: Rework session orchestration and bookkeeping in the job

**What**

Update `_process_session(...)` and the surrounding orchestration in
`jobs/session_memory_extraction.py` so the job:

- uses the previous successful boundary (`help_desk_processed_at`) when asking
  for a transcript delta,
- treats an empty delta as "no work" and exits without advancing bookkeeping,
- skips personal-memory extraction when identity scope cannot be resolved while
  still allowing business/actionable extraction to proceed,
- advances bookkeeping only after the extraction work for that session succeeds,
- removes the post-extraction `/compact` injection block entirely.

**Why**

This task aligns the job with the actual source-of-truth bookkeeping flow and
the approved requirements. It also contains the review-sensitive behavior:
correct high-water mark semantics, per-session failure isolation, no dead tmux
side effect, and no accidental coupling between the personal/business/actionable
lanes.

**Referenced files**

- `jobs/session_memory_extraction.py`
- `teleclaude/services/maintenance_service.py`

**Verification**

Make these tests GREEN:

- `test_process_session_returns_early_when_delta_is_empty`
- `test_process_session_uses_help_desk_processed_at_as_delta_boundary`
- `test_process_session_skips_personal_extraction_without_identity_key`
- `test_process_session_updates_bookkeeping_only_after_success`
- `test_process_session_does_not_inject_compact`
- `test_run_async_continues_after_per_session_failure`

## Task 3: Implement mirror-backed transcript delta reading

**What**

Replace `_read_transcript_delta(...)` with a mirror-backed reader that:

- loads the session mirror via `teleclaude.mirrors.store.get_mirror(...)`,
- reads the `transcript_path` from mirror metadata,
- resolves the mirror's `agent` into `AgentName`,
- calls `extract_structured_messages(...)` with the computed `since=` boundary,
- keeps only cleaned conversation text (`user`/`assistant`, `type == "text"`),
- strips system-reminder noise using the same normalization rules as the mirror
  generator,
- renders the result as human-readable `"User: ..."` / `"Assistant: ..."`
  blocks,
- returns `None` when there is no mirror, no transcript path, or no new
  conversation content.

**Why**

FR1 requires the delta reader to consume the mirror system's cleaned transcript
view rather than raw transcript files or tool noise. Reusing the mirror metadata
plus the existing transcript extractor keeps the implementation grounded in the
same normalization rules already used to build `conversation_text`, which avoids
parallel parsing logic and preserves the "clean conversation only" contract.

**Referenced files**

- `jobs/session_memory_extraction.py`
- `teleclaude/mirrors/store.py`
- `teleclaude/mirrors/generator.py`
- `teleclaude/utils/transcript/_tool_calls.py`
- `teleclaude/core/agents.py`

**Verification**

Make these tests GREEN:

- `test_read_transcript_delta_returns_none_without_mirror`
- `test_read_transcript_delta_returns_none_without_transcript_path`
- `test_read_transcript_delta_returns_none_without_new_messages`
- `test_read_transcript_delta_returns_clean_conversation_lines`

## Task 4: Implement structured personal and business memory extraction

**What**

Add local schema/prompt/parser helpers in `jobs/session_memory_extraction.py`
for the two memory lanes, then wire `_extract_personal_memories(...)` and
`_extract_business_memories(...)` to:

- call the existing `_call_summarizer(...)` helper with structured JSON schemas,
- map model output onto `ObservationInput` fields without changing the memory
  persistence interface,
- persist personal memories with `identity_key`,
- persist business memories without `identity_key`,
- derive project scope from the session's project context,
- treat "nothing worth storing" as a successful no-op,
- log-and-skip when the required scope for that lane is unavailable.

Keep the prompts bounded so they request a small number of durable observations
per run instead of broad freeform output; this keeps the implementation inside
the current summarizer contract without widening that helper's API.

**Why**

FR2 and FR3 share one existing pattern: structured summarizer call, validated
JSON response, `ObservationInput`, `MemoryStore.save_observation(...)`. Keeping
the schemas and parsers local to the job file preserves a narrow responsibility
boundary and avoids unapproved changes to the shared summarizer or memory
modules.

**Referenced files**

- `jobs/session_memory_extraction.py`
- `teleclaude/core/summarizer.py`
- `teleclaude/memory/store.py`
- `teleclaude/memory/types.py`

**Verification**

Make these tests GREEN:

- `test_extract_personal_memories_persists_identity_scoped_observations`
- `test_extract_personal_memories_skips_without_identity_key`
- `test_extract_personal_memories_noops_when_model_returns_no_memories`
- `test_extract_business_memories_persists_project_scoped_observations`
- `test_extract_business_memories_noops_when_model_returns_no_memories`

## Task 5: Implement actionable-item extraction and publication

**What**

Add the actionable-item schema/prompt/parser helpers in
`jobs/session_memory_extraction.py`, then wire
`_extract_and_publish_actionable_items(...)` to:

- extract structured actionable items through `_call_summarizer(...)`,
- build the target Redis stream key with `channel_key(project, "actionable-items")`,
- publish each extracted item through `teleclaude.channels.publisher.publish(...)`,
- preserve the extracted category and summary in the published payload,
- guard the transport path when Redis is disabled or unavailable,
- log-and-skip transport failures without aborting the rest of the session's
  extraction pipeline.

Use a small private helper in the job file for Redis client acquisition, grounded
in the same config/connection settings already used by the Redis transport.

**Why**

FR4 requires the channels subsystem boundary, but the cron job currently has no
reusable Redis acquisition helper. A narrow private helper inside the job keeps
the change local, avoids interface churn in the channels package, and still
reuses the canonical publisher API and channel-key builder.

**Referenced files**

- `jobs/session_memory_extraction.py`
- `teleclaude/channels/publisher.py`
- `teleclaude/config/__init__.py`
- `teleclaude/transport/redis_transport/_connection.py`

**Verification**

Make these tests GREEN:

- `test_extract_actionable_items_publishes_structured_payloads`
- `test_extract_actionable_items_noops_when_model_returns_no_items`
- `test_extract_actionable_items_skips_when_redis_is_disabled`
- `test_extract_actionable_items_logs_and_skips_transport_failures`

## Task 6: Final verification and demo alignment

**What**

After the code is GREEN, run the smallest verification surface that satisfies
the DoD for this todo and refresh `todos/session-memory-extraction/demo.md` only
where the final implementation changes command names or observable checkpoints.

**Why**

The reviewer will check not just correctness but also test discipline, linting,
observability, and demo validity. Capturing the targeted verification lane in the
plan prevents a builder from stopping after a single happy-path unit test.

**Referenced files**

- `tests/unit/test_session_memory_extraction.py`
- `todos/session-memory-extraction/demo.md`

**Verification**

Required builder checks:

- `python3 -m pytest tests/unit/test_session_memory_extraction.py -q`
- `python3 -m pytest tests/unit/services/test_maintenance_service.py -q -k idle_compaction`
- `telec todo demo validate session-memory-extraction`
- project hooks / lint / type-check path required by pre-commit for touched files

## Review Lanes To Anticipate

- **Functionality:** FR1-FR5 are all covered by explicit tasks and named tests.
- **Code quality:** no new shared abstraction, no summarizer API change, imports
  remain top-level, explicit types stay in the job/test file.
- **Testing:** builder works test-first in
  `tests/unit/test_session_memory_extraction.py`; no prose-lock assertions; keep
  mocks at architectural boundaries only.
- **Security and observability:** no secrets in logs; log skip/failure paths for
  missing identity scope, missing project scope, and Redis transport failure.
- **Documentation/demo:** `demo.md` stays valid for the final implementation;
  no CLI/config/doc-surface update is expected because this todo adds no new
  command or configuration surface.
