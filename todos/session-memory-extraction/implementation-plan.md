# Implementation Plan: session-memory-extraction

## Overview

Wire the four stubbed extraction methods in `jobs/session_memory_extraction.py` to use
the mirror system for transcript deltas and the existing `_call_summarizer` pattern for
LLM extraction. Each extraction step gets a dedicated JSON schema for structured output.
The `/compact` injection block is removed entirely.

The approach reuses every existing boundary — mirror store for reading, summarizer for
LLM calls, MemoryStore for persistence, channels publisher for actionable items — and
adds no new abstractions.

## Atomicity Decision

**Atomic.** All changes are in one file (`jobs/session_memory_extraction.py`) plus its
test file. The four stubbed methods are part of one pipeline that runs sequentially per
session. No new modules, no architectural decisions, no cross-cutting concerns. A single
builder session handles this comfortably.

---

## Task 1: Implement `_read_transcript_delta` (FR1)

**File(s):** `jobs/session_memory_extraction.py`

**What:** Replace the stub with a call to `mirrors.store.get_mirror(session_id)` to fetch
the session's mirror record, then return the `conversation_text` field. When `since` is
provided (prior extraction boundary exists), the full `conversation_text` must be trimmed
to only the content after that boundary.

**Why:** The mirror system already produces clean, human-readable conversation text with
tool noise and system reminders stripped. Using it avoids duplicating the transcript
cleaning logic and satisfies FR1's requirement that the data source be the mirror's
already-cleaned output. The mirror's `conversation_text` is a single rendered string
(not per-message rows with timestamps), so incremental windowing must be derived from
the mirror artifact and session bookkeeping — consistent with the [inferred] note in FR1.

**Implementation approach:**

- Import `get_mirror` from `teleclaude.mirrors.store`.
- Call `get_mirror(session_id=session_id)` to fetch the mirror record.
- If no mirror exists or `conversation_text` is empty, return `None`.
- When `since` is `None`, return the full `conversation_text` (first extraction).
- When `since` is provided, use a character-length delta strategy: slice
  `conversation_text[last_length:]` to get only new content, where `last_length` comes
  from the session's `last_extraction_mirror_length` field (persisted by Task 7).
  This avoids unreliable timestamp-based text searching on a rendered string.
- If the delta is empty or whitespace-only after slicing, return `None`.

**Note on incremental strategy:** The mirror stores a single `conversation_text` blob
that grows as the session progresses. Since mirrors don't expose per-message timestamps
in the rendered text, the cleanest incremental approach is tracking the character offset
of the last extraction. This requires adding a `last_extraction_mirror_length` integer
to the bookkeeping update. The alternative — parsing timestamps from rendered
"User: / Assistant:" lines — is fragile and couples extraction to rendering format.

**Verification:**
- Tests confirm: no mirror → returns `None`; mirror with empty text → returns `None`;
  first extraction (since=None) → returns full text; subsequent extraction with stored
  length → returns only new content; no new content → returns `None`.

---

## Task 2: Define extraction JSON schemas

**File(s):** `jobs/session_memory_extraction.py`

**What:** Define three module-level JSON schema constants for the structured output
responses: `PERSONAL_MEMORIES_SCHEMA`, `BUSINESS_MEMORIES_SCHEMA`, and
`ACTIONABLE_ITEMS_SCHEMA`. Each schema constrains the LLM output to an array of
typed objects that map directly to the persistence fields.

**Why:** The existing `_call_summarizer` pattern requires a JSON schema dict and a parser
function. Defining schemas up front keeps the extraction methods focused on orchestration.
Structured output schemas satisfy the constraint that "structured output schemas must be
used for the extraction prompts."

**Schema shapes:**

Personal memories schema:
```json
{
  "type": "object",
  "properties": {
    "memories": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "text": {"type": "string"},
          "type": {"type": "string", "enum": ["preference", "context", "pattern", "friction"]},
          "facts": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["title", "text", "type", "facts"],
        "additionalProperties": false
      }
    }
  },
  "required": ["memories"],
  "additionalProperties": false
}
```

Business memories schema — same structure but `type` enum values are
`["discovery", "context", "decision", "gotcha"]` (project-scoped observation types).

Actionable items schema:
```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "category": {"type": "string", "enum": ["bug", "feature-request", "follow-up", "escalation"]},
          "summary": {"type": "string"}
        },
        "required": ["category", "summary"],
        "additionalProperties": false
      }
    }
  },
  "required": ["items"],
  "additionalProperties": false
}
```

**Verification:** Schemas are valid JSON Schema. Parser functions correctly extract
the arrays from model responses. Empty arrays are handled as successful no-ops.

---

## Task 3: Implement `_extract_personal_memories` (FR2)

**File(s):** `jobs/session_memory_extraction.py`

**What:** Replace the stub with an LLM extraction call using `_call_summarizer` and
persist results via `MemoryStore.save_observation`.

**Why:** FR2 requires identity-scoped personal memories extracted via the existing
summarizer pattern. The method must skip extraction when `identity_key` is `None`
(no identity scope resolved) and log the reason — this prevents creating orphaned
personal memories with no owner.

**Implementation approach:**

- If `identity_key` is `None`, log a **warning** ("Personal memory extraction skipped: no identity scope resolved for session {session_id}") and return (FR2 skip-when-unresolvable).
- Build a prompt instructing the model to extract durable personal facts (preferences,
  communication style, domain knowledge, recurring needs) and explicitly exclude
  session-specific operational chatter.
- Call `_call_summarizer(prompt, PERSONAL_MEMORIES_SCHEMA, parser)`.
- For each extracted memory, create an `ObservationInput` with:
  - `text` = extracted text
  - `title` = extracted title
  - `project` = derived from `session.project_path`
  - `type` = mapped from schema enum to `ObservationType` value
  - `facts` = extracted facts list
  - `identity_key` = the resolved identity key
- Call `MemoryStore().save_observation(inp)` for each; log at **debug** level: "Saved personal memory: {title}".
- If the model returns an empty `memories` array, log at **debug** level and return (successful no-op).
- Wrap the LLM call in try/except; log at **error** level with exception and session_id, then return (pipeline continues).

**Verification:**
- Tests confirm: `identity_key=None` → skipped with warning log; empty model response → no saves with debug log;
  valid response → `save_observation` called with correct fields including `identity_key`, debug logged;
  LLM failure → error logged, pipeline continues.

---

## Task 4: Implement `_extract_business_memories` (FR3)

**File(s):** `jobs/session_memory_extraction.py`

**What:** Replace the stub with LLM extraction for project-scoped business facts,
persisted without identity scope.

**Why:** FR3 mirrors FR2's structure but targets project-level knowledge. Business
memories are shared across the project — no `identity_key` is set. This captures
product feedback, pain points, feature requests, and domain context.

**Implementation approach:**

- Build a prompt focused on project-level business facts.
- Call `_call_summarizer(prompt, BUSINESS_MEMORIES_SCHEMA, parser)`.
- For each extracted memory, create an `ObservationInput` with:
  - `text`, `title`, `facts` from extraction
  - `project` = derived from `session.project_path`
  - `type` = mapped `ObservationType` value
  - `identity_key` = `None` (explicitly unscoped)
- Call `MemoryStore().save_observation(inp)` for each; log at **debug** level: "Saved business memory: {title}".
- If empty array, log at **debug** level and return (successful no-op).
- Wrap in try/except; log at **error** level with exception and session_id, then return (pipeline continues).

**Verification:**
- Tests confirm: empty response → no saves with debug log; valid response → `save_observation` called
  without `identity_key`, debug logged; project derived from session; LLM failure → error logged, pipeline continues.

---

## Task 5: Implement `_extract_and_publish_actionable_items` (FR4)

**File(s):** `jobs/session_memory_extraction.py`

**What:** Replace the stub with LLM extraction for actionable items, published to
the channels subsystem via Redis Streams.

**Why:** FR4 requires actionable follow-ups (bugs, feature requests, follow-ups,
escalations) to be published through the channels subsystem for downstream routing.
The channels publisher is the existing boundary — `publish(redis, channel_key, payload)`.

**Implementation approach:**

- Build a prompt focused on identifying actionable items with category and summary.
- Call `_call_summarizer(prompt, ACTIONABLE_ITEMS_SCHEMA, parser)`.
- If items are found:
  - Obtain a Redis client via `RedisTransport` (import from
    `teleclaude.transport.redis_transport`). Check if Redis is available first.
  - For each item, call `publish(redis, channel_key(project, "actionable-items"), payload)`
    where payload includes `category`, `summary`, `session_id`, and optionally `identity_key`.
    Log at **info** level: "Published actionable item ({category}): {summary}".
- If Redis is unavailable (not configured or connection fails), log a **warning** ("Redis unavailable for actionable-items publishing; skipping session {session_id}") and skip publication — do not crash the pipeline (FR4 constraint + AC on channels unavailability).
- If empty array, log at **debug** level and return (successful no-op).
- Wrap the entire block in try/except; log at **error** level with exception and session_id, then return (pipeline continues).

**Verification:**
- Tests confirm: empty items → no publish, debug logged; valid items → `publish` called with correct
  channel key and payload, info logged per item; Redis unavailable → warning logged, skipped, no crash; LLM failure → error logged, pipeline continues.

---

## Task 6: Remove `/compact` injection (FR5)

**File(s):** `jobs/session_memory_extraction.py`

**What:** Delete the entire Step 7 block in `_process_session` that injects `/compact`
into the tmux pane after extraction.

**Why:** FR5 states the post-extraction `/compact` injection must be removed because no
handler exists for it. The comment in the code references this dead path. No replacement
is introduced.

**Implementation approach:**

- Remove lines 147–159 (the Step 7 block) from `_process_session`.
- Remove the `tmux_bridge` import that becomes unused.
- Renumber the remaining step comments if desired for clarity.

**Verification:**
- No reference to `/compact` or `send_keys_existing_tmux` remains in the file.
- `_process_session` ends after `_update_bookkeeping`.

---

## Task 7: Add session schema field and update bookkeeping for mirror-length tracking

**File(s):** `teleclaude/core/models/_session.py`, `teleclaude/core/db_models.py`, `jobs/session_memory_extraction.py`

**What:** Add the `last_extraction_mirror_length` integer field to the Session model,
then extend `_update_bookkeeping` to persist this value during extraction.

**Why:** Task 1's incremental strategy requires knowing where the last extraction ended
in the mirror text. The Session model currently tracks `last_memory_extraction_at` but
not the mirror text length. Adding this field keeps extraction bookkeeping atomic
(both timestamp and length advance together) and enables deterministic incremental
reads on subsequent runs.

**Implementation approach:**

- Add `last_extraction_mirror_length: int | None = None` to the Session dataclass in
  `teleclaude/core/models/_session.py` (after `last_memory_extraction_at`).
- Verify the corresponding database model in `teleclaude/core/db_models.py` includes
  this optional integer column, or add it if missing.
- Update `_update_bookkeeping` in `jobs/session_memory_extraction.py` to accept a
  `mirror_text_length` parameter.
- Persist it via `db.update_session(session_id, last_extraction_mirror_length=length)`.
- Update the call site in `_process_session` to pass the full mirror text length after
  all extractions complete (only after success; bookkeeping is NOT updated if any
  extraction fails).

**Verification:**
- Session model change compiles (type checker passes).
- After extraction, stored length matches the mirror's `conversation_text` length.
- On re-run with no new content, `_read_transcript_delta` returns `None`.
- Test confirms idempotency: re-running the same extraction window produces no duplicate memories.

---

## Task 8: Add prompt-building helpers

**File(s):** `jobs/session_memory_extraction.py`

**What:** Add three private functions that build the extraction prompts:
`_build_personal_memory_prompt`, `_build_business_memory_prompt`,
`_build_actionable_items_prompt`. Each takes the transcript delta as input and
returns the prompt string.

**Why:** Separating prompt construction from orchestration keeps the extraction methods
readable and makes prompts independently testable. The prompts define the extraction
quality — they must be specific about what to extract and what to exclude.

**Prompt design principles:**
- Personal: focus on durable cross-project facts about the person. Exclude session ops.
- Business: focus on project-level product/domain knowledge. Exclude personal traits.
- Actionable: focus on concrete follow-ups with clear categories. Exclude vague wishes.
- All prompts instruct the model to return an empty array when nothing qualifies.

**Verification:**
- Prompts include clear extraction criteria and exclusion rules.
- Empty transcript delta edge case is handled (though the caller already filters this).

---

## Task 9: Add parser functions

**File(s):** `jobs/session_memory_extraction.py`

**What:** Add three parser functions that the `_call_summarizer` pattern requires:
`_parse_personal_memories`, `_parse_business_memories`, `_parse_actionable_items`.
Each parses JSON text into typed Python structures.

**Why:** The `_call_summarizer` takes a parser callback that converts raw JSON text
from the model into the expected Python types. Parsers validate the response shape
and raise on malformed output (triggering the summarizer's fallback to the next provider).

**Verification:**
- Valid JSON → correct typed output.
- Missing required fields → `ValueError` raised.
- Empty arrays → returned as empty lists (successful no-op path).

---

## Task 10: Write tests

**File(s):** `tests/jobs/test_session_memory_extraction.py`

**What:** Comprehensive test suite covering all extraction paths, edge cases, and
error handling.

**Why:** DoD requires tests for all new behavior. The extraction pipeline has multiple
code paths (no mirror, empty delta, no identity key, empty model response, valid extraction,
Redis unavailable, per-session error isolation) that each need coverage.

**Test cases:**

1. `_read_transcript_delta` — no mirror → `None`
2. `_read_transcript_delta` — mirror with empty text → `None`
3. `_read_transcript_delta` — first extraction → full text
4. `_read_transcript_delta` — incremental extraction → delta only
5. `_read_transcript_delta` — no new content → `None`
6. `_extract_personal_memories` — no identity key → skipped
7. `_extract_personal_memories` — empty model response → no saves
8. `_extract_personal_memories` — valid extraction → saves with identity key
9. `_extract_business_memories` — empty response → no saves
10. `_extract_business_memories` — valid extraction → saves without identity key
11. `_extract_and_publish_actionable_items` — empty response → no publish
12. `_extract_and_publish_actionable_items` — valid items → published
13. `_extract_and_publish_actionable_items` — Redis unavailable → skipped with log
14. `_process_session` — no `/compact` injection (FR5 regression guard)
15. `_process_session` — single session error does not block others
16. `_process_session` — bookkeeping advances only after successful extraction
17. Parser functions — valid JSON, malformed JSON, empty arrays
18. Schema constants — valid JSON Schema structure

**Mocking boundaries:**
- `teleclaude.mirrors.store.get_mirror` — mock the mirror lookup
- `teleclaude.core.summarizer._call_summarizer` — mock the LLM call
- `teleclaude.memory.store.MemoryStore.save_observation` — mock persistence
- `teleclaude.channels.publisher.publish` — mock channel publishing
- `teleclaude.core.db.db` — mock session queries and bookkeeping updates
- Redis client availability — mock transport

**Verification:** All tests pass. No flaky tests. Each test targets one behavioral path.

---

## Risks

- **Mirror text length tracking requires a new session field.** If
  `last_extraction_mirror_length` doesn't exist in the session schema, it must be added
  as an optional integer column. This is a minimal schema addition. If adding the column
  is blocked, the fallback is to always process the full mirror text (safe but
  re-processes content).
- **LLM prompt quality.** Extraction signal depends on prompt design. Mitigated by
  structured output schemas that constrain response shape and by the existing
  dual-provider fallback in `_call_summarizer`.
- **Mirror text growth.** Very long sessions produce large `conversation_text` blobs.
  The delta strategy limits what's sent to the LLM on subsequent runs, but the first
  extraction of a long session sends the full text. Token limits in `_call_summarizer`
  (currently `max_tokens=200`) may need to be higher for extraction responses. The builder
  should set `max_tokens` appropriately for array responses.
