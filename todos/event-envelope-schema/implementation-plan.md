# Implementation Plan: event-envelope-schema

## Overview

The `EventEnvelope` model in `teleclaude_events/envelope.py` already implements the
five-layer structure. This plan hardens the schema through four phases: expansion joint,
core taxonomy, versioning, and JSON Schema export. All changes are additive and
backward-compatible with existing consumers.

## Phase 1: Expansion Joint (extra fields)

### Task 1.1: Enable extra fields on EventEnvelope

**File(s):** `teleclaude_events/envelope.py`

- [ ] Add `model_config = ConfigDict(extra="allow")` to `EventEnvelope`
- [ ] Update `to_stream_dict()` to collect extra fields into a JSON-encoded `_extra` key
- [ ] Update `from_stream_dict()` to deserialize `_extra` back into model extra fields

### Task 1.2: Update EventDB for extra field storage

**File(s):** `teleclaude_events/db.py`

- [ ] Verify the `payload` column (JSON) can carry extra fields if needed, OR
      confirm extra fields are envelope-level and do not affect notification projection
- [ ] No schema migration needed — extra fields live on the envelope, not in SQLite

---

## Phase 2: Core Event Taxonomy

### Task 2.1: Register node lifecycle events

**File(s):** `teleclaude_events/schemas/node.py` (new)

- [ ] Create `register_node(catalog)` with:
  - `node.alive` — heartbeat/presence (INFRASTRUCTURE, CLUSTER)
  - `node.leaving` — graceful departure (INFRASTRUCTURE, CLUSTER)
  - `node.descriptor_updated` — node metadata changed (OPERATIONAL, CLUSTER)

### Task 2.2: Register deployment lifecycle events

**File(s):** `teleclaude_events/schemas/deployment.py` (new)

- [ ] Create `register_deployment(catalog)` with:
  - `deployment.started` — deploy initiated (WORKFLOW, LOCAL)
  - `deployment.completed` — deploy succeeded (WORKFLOW, LOCAL)
  - `deployment.failed` — deploy failed (BUSINESS, LOCAL, actionable)
  - `deployment.rolled_back` — rollback executed (WORKFLOW, LOCAL)

### Task 2.3: Register content lifecycle events

**File(s):** `teleclaude_events/schemas/content.py` (new)

- [ ] Create `register_content(catalog)` with:
  - `content.dumped` — raw content captured (WORKFLOW, LOCAL)
  - `content.refined` — content processed/edited (WORKFLOW, LOCAL)
  - `content.published` — content made available (BUSINESS, LOCAL)

### Task 2.4: Register notification meta-events

**File(s):** `teleclaude_events/schemas/notification.py` (new)

- [ ] Create `register_notification(catalog)` with:
  - `notification.escalation` — escalated to human (BUSINESS, LOCAL, actionable)
  - `notification.resolution` — escalation resolved (WORKFLOW, LOCAL)

### Task 2.5: Register schema evolution events

**File(s):** `teleclaude_events/schemas/schema.py` (new)

- [ ] Create `register_schema(catalog)` with:
  - `schema.proposed` — schema change proposed (OPERATIONAL, CLUSTER)
  - `schema.adopted` — schema change merged (OPERATIONAL, CLUSTER)

### Task 2.6: Wire new schemas into catalog

**File(s):** `teleclaude_events/schemas/__init__.py`

- [ ] Import and call all new `register_*` functions in `register_all()`

---

## Phase 3: Schema Versioning

### Task 3.1: Define SCHEMA_VERSION constant

**File(s):** `teleclaude_events/envelope.py`

- [ ] Add `SCHEMA_VERSION: int = 1` constant at module level
- [ ] Update `EventEnvelope.version` field default to use `SCHEMA_VERSION`
- [ ] Add a docstring explaining that SCHEMA_VERSION tracks the envelope structure
      generation and is bumped when fields are added/removed/changed

---

## Phase 4: JSON Schema Export

### Task 4.1: Add schema export utility

**File(s):** `teleclaude_events/schema_export.py` (new)

- [ ] Create `export_json_schema() -> dict` that returns `EventEnvelope.model_json_schema()`
- [ ] Create `export_json_schema_file(path: Path) -> None` that writes the schema to disk
- [ ] Include a `if __name__ == "__main__"` block for CLI invocation:
      `python -m teleclaude_events.schema_export [output_path]`

---

## Phase 5: Validation

### Task 5.1: Tests for expansion joint

**File(s):** `tests/test_event_envelope_schema.py` (new)

- [ ] Test: extra fields survive `EventEnvelope` construction
- [ ] Test: extra fields round-trip through `to_stream_dict()` → `from_stream_dict()`
- [ ] Test: extra fields do not appear in the base model's declared fields

### Task 5.2: Tests for core taxonomy

**File(s):** `tests/test_event_envelope_schema.py`

- [ ] Test: all root families are registered in `build_default_catalog()`
- [ ] Test: each registered event type has required fields (description, level, domain)
- [ ] Test: idempotency key generation works for new event types

### Task 5.3: Tests for schema versioning

**File(s):** `tests/test_event_envelope_schema.py`

- [ ] Test: `SCHEMA_VERSION` equals the expected value
- [ ] Test: default `EventEnvelope().version` matches `SCHEMA_VERSION`

### Task 5.4: Tests for JSON Schema export

**File(s):** `tests/test_event_envelope_schema.py`

- [ ] Test: `export_json_schema()` returns a valid JSON Schema dict
- [ ] Test: the exported schema validates a real envelope from the catalog
- [ ] Run `make test`

### Task 5.5: Quality checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 6: Documentation

### Task 6.1: Update event vocabulary spec

**File(s):** `docs/project/spec/event-vocabulary.md`

- [ ] Add a "Core Event Taxonomy" section listing the root families and their schemas
- [ ] Add an "Expansion Joint" section documenting the additional-properties mechanism
- [ ] Reference the JSON Schema export path for external consumers

---

## Phase 7: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
