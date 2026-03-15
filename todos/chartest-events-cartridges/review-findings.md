# Review Findings: chartest-events-cartridges

## Scope

Lane: scope verification (reviewer direct)

Requirements list 8 source files and the delivery includes 8 corresponding test files under `tests/unit/events/cartridges/`. All implementation-plan tasks are checked `[x]`. No `deferrals.md` exists. The diff stays within tests plus todo/demo artifacts; no production code was modified.

No findings.

## Code

Lane: code review (reviewer direct + explorer review passes)

No additional code-review findings beyond the test-quality issues captured in the Tests lane.

## Paradigm

Lane: paradigm-fit assessment (reviewer direct)

The new tests follow the repo's cartridge-test pattern: module docstring, local event/context factories, and async `process()` characterization at the module boundary where the coverage is meaningful.

No findings.

## Principles

Lane: principle violation hunt (reviewer direct)

No production-code principle violations were introduced in this delivery. The main review risk is test-boundary drift: several tests characterize helpers and mocked internals rather than the public contract that future refactors are expected to preserve. Those issues are recorded in the Tests lane rather than duplicated here.

No additional findings.

## Security

Lane: security review (reviewer direct)

No secrets, credentials, or sensitive payloads were introduced. The diff adds only test fixtures and markdown artifacts. No command injection, SQL injection, or authorization surfaces changed.

No findings.

## Tests

Lane: test coverage analysis (reviewer direct + explorer review passes)

Verification run during review:

- `uv run pytest tests/unit/events/cartridges/ -q --tb=short` -> 81 passed
- `uv run pytest tests/unit/events/cartridges/ --cov=teleclaude.events.cartridges.classification --cov=teleclaude.events.cartridges.correlation --cov=teleclaude.events.cartridges.dedup --cov=teleclaude.events.cartridges.enrichment --cov=teleclaude.events.cartridges.integration_trigger --cov=teleclaude.events.cartridges.notification --cov=teleclaude.events.cartridges.prepare_quality --cov=teleclaude.events.cartridges.trust --cov-branch --cov-report=term-missing -q`

### Important

1. **`tests/unit/events/cartridges/test_prepare_quality.py:10-18,186-333` does not characterize the cartridge's primary public behavior.**
   The file imports and asserts private helpers (`_build_dependency_section`, `_fill_plan_gaps`, `_fill_requirements_gaps`, `_is_slug_delivered_or_frozen`) and only exercises `PrepareQualityCartridge.process()` on early-return/error paths. The actual public work in `teleclaude/events/cartridges/prepare_quality.py:396-572` — scoring artifacts, writing `dor-report.md`, updating `state.yaml`, claiming/resolving notifications, and emitting `domain.software-development.planning.dor_assessed` — is untested. The review coverage run reflects that gap: `prepare_quality.py` is only 54.09% covered.

2. **`tests/unit/events/cartridges/test_integration_trigger.py:43-60,147-177` leaves the public integration contract partially unpinned.**
   `IntegrationTriggerCartridge.process()` strips underscore-prefixed pipeline metadata before invoking ingest and maps `domain.software-development.deployment.started` to `finalize_ready` (`teleclaude/events/cartridges/integration_trigger.py:78-100`). The suite never drives a `deployment.started` event through `process()`, and payload sanitization is asserted only via the private helper `_strip_pipeline_metadata` rather than via `process()`. A regression in either the canonical mapping or metadata stripping can slip through while these tests still pass.

3. **`tests/unit/events/cartridges/test_correlation.py:30-56,73-207` mocks away the time-window contract it is supposed to characterize.**
   `CorrelationCartridge.process()` depends on correct `older_than`, `window_start`, and `entity` arguments when calling `prune_correlation_windows`, `increment_correlation_window`, and `get_correlation_count` (`teleclaude/events/cartridges/correlation.py:44-87`). The tests inject canned counts and assert on emitted synthetic events, but they never assert those DB call arguments. A regression that queries the wrong window or entity would still satisfy the current suite.

4. **`tests/unit/events/cartridges/test_dedup.py:27-40,70-137` and `tests/unit/events/cartridges/test_enrichment.py:74-156` do not pin the catalog/DB query inputs that define the behavior.**
   `DeduplicationCartridge.process()` relies on `context.catalog.build_idempotency_key(event.event, event.payload)` (`teleclaude/events/cartridges/dedup.py:17-35`), while `EnrichmentCartridge` relies on exact query parameters such as `payload_filter={"success": False}`, the `system.worker.crashed` event name, and the 24-hour cutoff (`teleclaude/events/cartridges/enrichment.py:50-69`). The tests stub return values but never assert the input arguments sent to those collaborators, so wrong key generation or wrong enrichment queries would still pass.

## Errors

Lane: silent failure analysis (reviewer direct)

The changed tests do not introduce new silent-failure patterns of their own. Existing swallow/log-and-continue behavior in the cartridges is part of the current production behavior and is appropriately noted where tested.

No findings.

## Types

Lane: type design analysis (reviewer direct)

The changed Python tests use explicit return types where needed, parameterized generics, and top-level imports. No type-design issues surfaced in the review.

No findings.

## Comments

Lane: comment analysis (reviewer direct)

Module docstrings correctly identify the source modules they characterize. Inline comments are sparse and accurate.

No findings.

## Logging

Lane: logging review (reviewer direct)

No ad-hoc debug probes, `print()`, or stray logging calls were added in the changed tests or task artifacts.

No findings.

## Demo

Lane: demo artifact review (reviewer direct)

### Resolved During Review

1. **`todos/chartest-events-cartridges/demo.md:5-27` and `demos/chartest-events-cartridges/demo.md:5-27` masked failing test exits.**
   The original demo blocks piped `pytest` into `tail`/`grep`/`head`. `telec todo demo run` executes those blocks with `subprocess.run(..., shell=True)` at `teleclaude/cli/telec/handlers/demo.py:239`, so the shell would report the status of the last pipeline command instead of `pytest`. During review I replaced those blocks with direct `./.venv/bin/python -m pytest ...` invocations and revalidated the artifact.

No remaining demo findings.

## Simplify

Lane: simplify review (reviewer direct)

No additional safe simplifications were identified beyond the demo hardening performed during review.

No findings.

## Manual Verification

- `telec todo demo validate chartest-events-cartridges` -> passed after review-side demo hardening
- `./.venv/bin/python -m pytest tests/unit/events/cartridges/test_classification.py tests/unit/events/cartridges/test_trust.py tests/unit/events/cartridges/test_dedup.py -q --tb=short` -> 20 passed
- `./.venv/bin/python -m pytest tests/unit/events/cartridges/ --collect-only -q` -> 81 tests collected

---

**Verdict: REQUEST CHANGES**

Critical: 0
Important: 4
Suggestions: 0
