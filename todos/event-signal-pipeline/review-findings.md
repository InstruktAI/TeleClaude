# Review Findings: event-signal-pipeline

## Verdict: APPROVE

---

## Critical

### C1. Cluster and synthesize cartridges constructed but never registered with the pipeline

**Location:** `teleclaude/daemon.py:1905-1931`

The `SignalClusterCartridge` and `SignalSynthesizeCartridge` are instantiated but then assigned to `_` (discarded) with misleading comments ("registered with pipeline below"). No registration code exists. The `Pipeline` is constructed at line 1830-1843 with only the core cartridges; the signal cartridges are not included.

**Impact:** The entire clustering and synthesis stages are dead code. The `IngestScheduler` runs and emits `signal.ingest.received` events, but those events flow through the main pipeline which has no signal cartridges registered. `signal.cluster.formed` and `signal.synthesis.ready` events are never emitted. The `signal_clusters` and `signal_syntheses` tables remain empty indefinitely. Items accumulate in `signal_items` with `cluster_id IS NULL` forever.

**Principle violated:** Silent degradation (Fail Fast, Failure Modes). The pipeline reports success at startup ("Signal pipeline started") while two of three processing stages are non-functional.

**Remediation:** Register both cartridges with the `Pipeline` in the correct order (cluster after ingest, synthesize after cluster), or if the Pipeline API doesn't support late registration, add them to the cartridge list at construction.

### C2. `DefaultSignalAIClient.synthesise_cluster` returns fake success artifact on failure

**Location:** `teleclaude_events/signal/ai.py:119-128`

On any exception (network, auth, rate limit, JSON parse), the method returns a structurally valid `SynthesisArtifact` with `summary="Cluster synthesis unavailable."` and `confidence=0.0`. The caller (`SignalSynthesizeCartridge.process`) persists this to the database and emits a `signal.synthesis.ready` event with the stub artifact.

**Impact:** Synthesis failures produce semantically misleading events and corrupt database records. Downstream consumers of `signal.synthesis.ready` receive garbage data. The `confidence=0.0` field provides some signal, but the event name "ready" and the fact it's persisted as a real record makes this a data integrity issue. Log severity is `WARNING` for what should be `ERROR`.

**Principle violated:** Fail Fast, Silent degradation.

**Remediation:** Let the exception propagate. `SignalSynthesizeCartridge.process` should catch, log at ERROR with cluster_id context, and return the original event (pass through without synthesis) rather than emitting a fake "ready" event. Failed syntheses should not be persisted to `signal_syntheses`.

---

## Important

### I1. Signal pipeline startup `except Exception` at WARNING severity

**Location:** `teleclaude/daemon.py:1932-1933`

The entire signal pipeline startup block is wrapped in `except Exception` logged at `WARNING`. A complete subsystem disabling itself is an `ERROR`-level event. Monitoring systems alerting on ERROR will not fire.

**Remediation:** Log at `ERROR`. Separate `ImportError` (optional dependency missing, appropriate at WARNING) from other exceptions (bugs, auth failures, config errors — these are ERROR).

### I2. `extract_tags` returns `["general"]` on failure, corrupting clustering

**Location:** `teleclaude_events/signal/ai.py:77-79`

When tagging fails, all items get `["general"]`. Since `group_by_tags` groups by tag overlap, every failed item matches every other failed item on the `"general"` tag, creating artificial clusters from unrelated content.

**Remediation:** Return `[]` on failure, not `["general"]`. Callers should handle empty tag lists as a disqualifier for tag-based grouping.

### I3. `summarise` returns truncated title as fallback without distinguishability

**Location:** `teleclaude_events/signal/ai.py:57-59`

On failure, `title[:100]` is returned and stored as the item's summary. This degraded value propagates through clustering and synthesis with no way for consumers to distinguish it from a real AI summary.

**Remediation:** Return `None` or raise. Callers should skip items that lack a real summary, or store a separate flag indicating degraded enrichment.

### I4. Cluster summary fallback persists raw title list

**Location:** `company/cartridges/signal/cluster.py:80-84`

On AI failure, `summary_prompt[:200]` (semicolon-joined raw titles) is persisted as the cluster summary and used in the `signal.cluster.formed` event description. Not distinguishable from a real summary in the database.

**Remediation:** On failure, skip cluster formation for this pass. The next scheduler pass will re-attempt.

### I5. Blocking file I/O in async call chain

**Location:** `teleclaude_events/signal/sources.py:87` (called from `ingest.py:43`)

`Path.read_text()` is a blocking call inside the async `pull()` method. The requirements constraint states: "All I/O async; no blocking calls in cartridge `process()`". `load_sources()` is called on every pull cycle (default 15 min), reading and parsing OPML/CSV files synchronously.

**Remediation:** Use `aiofiles` or `asyncio.to_thread()` for file reads, or cache the parsed sources after first load.

### I6. `fetch_full_content` HTML parsing error caught without logging

**Location:** `teleclaude_events/signal/fetch.py:77-82`

Bare `except Exception` with zero logging. The regex fallback includes script/style content (bypass of `_TextExtractor` filtering), degrading content quality silently.

**Remediation:** Add at minimum `logger.warning("HTML parse fallback for %s: %s", url, e)`.

### I7. `parse_rss_feed` returns `[]` on parse error without logging

**Location:** `teleclaude_events/signal/fetch.py:137-140`

A malformed XML feed silently returns an empty list. The caller (`ingest.py`) proceeds with zero items and no log. A broken feed is indistinguishable from an empty feed.

**Remediation:** Log at `logger.warning` with content length. The caller in `ingest.py` should log the source URL when a non-empty body produces zero items.

### I8. `IngestScheduler` has zero test coverage

**Location:** `teleclaude_events/signal/scheduler.py`

No tests for shutdown behavior, exception handling in the loop, `CancelledError` re-raise, or interval timing. A regression where `CancelledError` is caught rather than re-raised would hang daemon shutdown.

**Remediation:** Add unit tests covering: shutdown event stops loop, pull exceptions don't kill loop, CancelledError propagates.

### I9. Enrichment errors logged without item context

**Location:** `company/cartridges/signal/ingest.py:113-117`

`logger.error("Ingest enrichment error: %s", r, exc_info=r)` — `exc_info=r` with an exception instance is non-standard (expects `True` or a tuple). The log contains no information about which item URL or idempotency key failed.

**Remediation:** Use `exc_info=True`. Include `ikey` and item URL in the log message.

---

## Suggestions

### S1. `ClusteringConfig.singleton_promote_after_seconds` defined but unused

**Location:** `teleclaude_events/signal/clustering.py:18`

Config field exists in the model but is never referenced in any algorithm or cartridge code. Dead config.

### S2. Dead `TYPE_CHECKING` block in `ai.py`

**Location:** `teleclaude_events/signal/ai.py:10-11`

```python
if TYPE_CHECKING:
    pass
```

Empty guard block — remove.

### S3. Import ordering in `synthesize.py`

**Location:** `company/cartridges/signal/synthesize.py:16`

`from pydantic import BaseModel` is placed after the `TYPE_CHECKING` block instead of at module top with other third-party imports.

### S4. `embed()` debug log fires on every item

**Location:** `teleclaude_events/signal/ai.py:83`

Produces N log entries per pull cycle (one per item), all saying the same thing. Should log once at startup at `WARNING` level that embedding-based clustering is disabled.

### S5. `_near_duplicate` has no direct unit tests

**Location:** `company/cartridges/signal/synthesize.py:27-34`

Only tested indirectly through the cartridge integration test. Edge cases (empty strings, threshold boundaries) are not covered.

### S6. Source config validation tests use bare `Exception`

**Location:** `tests/unit/test_signal/test_sources.py:124-130`

`pytest.raises(Exception)` should be `pytest.raises(ValidationError, match=...)` for specificity.

### S7. `enrich_and_emit` uses `nonlocal count` with concurrent gather

**Location:** `company/cartridges/signal/ingest.py:68`

While safe in asyncio (single-threaded), it's a code smell. Consider returning counts from tasks and summing after gather.

---

## Paradigm-Fit Assessment

- **Data flow:** Implementation follows established event platform patterns (EventEnvelope, PipelineContext, Cartridge protocol). Correct.
- **Component reuse:** Uses existing EventDB, EventCatalog, Pipeline. No copy-paste duplication. Correct.
- **Pattern consistency:** Schema registration follows existing pattern. Daemon wiring follows existing background task pattern. Correct.
- **Import boundary:** No `teleclaude.*` imports in `company/cartridges/signal/` or `teleclaude_events/signal/` — verified clean.

---

## Requirements Tracing

| Requirement | Status | Notes |
|---|---|---|
| signal-ingest pulls RSS, creates events | Implemented | Tested |
| Duplicate items skipped on re-pull | Implemented | Tested |
| AI summary in description, tags in payload | Implemented | Tested |
| signal-cluster groups ingested items | Implemented but dead | C1: Not wired into pipeline |
| signal.cluster.formed with burst/novelty flags | Implemented but dead | C1: Never executes in daemon |
| signal-synthesize produces synthesis artifact | Implemented but dead | C1: Never executes in daemon |
| signal.synthesis.ready creates notification | Implemented but dead | C1: Never emitted |
| Source config from OPML and CSV | Implemented | Tested |
| All three cartridges loadable via Pipeline | NOT MET | C1: Only ingest scheduler runs |
| make test passes | Met | 3104 passed |
| make lint passes | Met | Score 9.39/10 |
| No teleclaude imports in signal code | Met | Verified |

---

---

## Fixes Applied

### C1 — Cluster/synthesize cartridges registered with pipeline
Added `Pipeline.register()` method and called it for both cartridges after `IngestScheduler` startup. Signal events now flow through the full ingest→cluster→synthesize chain.
**Commit:** `a181f3527`

### C2 — synthesise_cluster propagates exceptions
Removed fake `SynthesisArtifact` fallback. `synthesise_cluster()` re-raises (logging at ERROR). `SignalSynthesizeCartridge.process()` catches, logs with `cluster_id` at ERROR, and returns the original event (pass-through). No corrupt DB records, no misleading `signal.synthesis.ready`.
**Commit:** `93248a61b`

### I1 — Startup exception severity
Separated `ImportError` (WARNING — optional dep missing) from other exceptions (ERROR). Monitoring alerts will now fire on real failures.
**Commit:** `9f01d3cd7`

### I2 — extract_tags returns [] on failure
Removed `or ["general"]` fallback. Both the success path (empty result) and failure path now return `[]`, preventing artificial clusters.
**Commit:** `95a341638`

### I3 — summarise raises on failure
Re-raises instead of returning `title[:100]`. Failed items are skipped cleanly via `asyncio.gather` error handling in `enrich_and_emit`.
**Commit:** `c309e7948`

### I4 — Skip cluster formation on AI failure
`continue` instead of using raw joined titles as summary. Cluster retried on next scheduler pass.
**Commit:** `3b1336b4d`

### I5 — Async file I/O in load_sources
`load_sources` is now `async`, using `asyncio.to_thread` for `Path.read_text`. Callers and tests updated. Pre-existing spec omission for `signals` CLI command also fixed here.
**Commit:** `f9fb12651`

### I6 + I7 — Logging in fetch.py
HTML parse fallback now logs at WARNING with URL and exception. RSS parse errors log content length and error. Ingest logs when non-empty body produces zero items.
**Commit:** `bc06e4533`

### I8 — IngestScheduler unit tests
Added `tests/unit/test_signal/test_scheduler.py` with 4 tests: shutdown stops loop, pull executes after interval, pull exceptions don't kill loop, CancelledError propagates.
**Commit:** `fc268b5ce`

### I9 — Enrichment error logging fixed
`exc_info=True` replaces non-standard `exc_info=r`. Errors now include `ikey` and item URL via `zip(results, new_items)`.
**Commit:** `32ef50d6b`

### S2 + S3 + S4 — Cleanup
Removed dead `TYPE_CHECKING` block, fixed pydantic import ordering, removed per-call embed debug log.
**Commit:** `0c6644ab3`

---

## Demo Artifact Review

The demo has 8 executable blocks covering: schema registration, cartridge imports, source config, DB tables, RSS parsing, import boundary, tests, and lint. The blocks exercise real code paths and are structurally correct.

**Gap:** The demo does not exercise the actual cartridge pipeline end-to-end (ingest -> cluster -> synthesize). This is consistent with C1 — since the cartridges are not wired in the daemon, an end-to-end demo would fail. The demo proves individual components work in isolation but does not prove the pipeline works as an integrated system.

**Verdict on demo:** The demo is honest about what works (components in isolation) but does not surface the integration gap. This is acceptable given the demo scope, but the pipeline integration gap (C1) must be resolved.
