---
description: 'Python-specific testing idioms layered over the generic testing policy: pytest runner, file/marker conventions, snapshots, and the no-unit-test enforcement.'
visibility: 'public'
---

# Python Testing — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md

## Rules

1. **No unit tests.** Behavior is verified by functional and smoke tests; Python is a compiler-less
   language under the generic rule. A unit test placed anywhere, or wearing a `@pytest.mark.functional`
   label, is caught at review against `software-development/concept/functional-test-boundary`. The
   discipline lives in the definition and the review.
2. **Test files mirror the feature spec.** A spec at `docs/project/spec/feature/<domain>/<slug>.md`
   is covered by `tests/<domain>/test_<slug>.py`. Contract-defining tooling (wrappers, git filters)
   is not tested — see the generic policy.
3. **Bind scenarios with the marker** `@pytest.mark.spec("<spec_id>", "<UC-id>")`.
   The functional/integration/process tier is a marker (`@pytest.mark.functional` /
   `@pytest.mark.integration` / `@pytest.mark.process`), never a directory — a directory may
   _organize_ a tier's tests (e.g. `tests/process/`), but tier selection is always by marker. The
   `process` tier marks a test that drives a real OS subprocess across wall-clock deadlines.
   Shared fixtures live in `tests/conftest.py`.
4. **Run via `uv run pytest`.** The harness is plain pytest plus declarative configuration. Tests run
   in tiers under non-negotiable time budgets owned by the harness config: the fast tier
   (functional/integration) excludes the `process` tier so a subprocess-timing test never starves it,
   and the `process` tier runs as a separate serial stage under its own bounded budget. A test that
   exceeds its budget is fixed, split, or retiered — never granted a larger budget. A test that can
   hang or leak is fixed (or moved to a self-cleaning integration test), not wrapped in harness code.
5. **Snapshots use `syrupy`**; CI never updates snapshots. The string-assertion paradigm is the
   generic policy's.
6. **Coverage** is measured against the scenario inventory; drift is handled by the spec → test →
   code change process (generic policy rule 10).
7. **Async tests synchronize on conditions, never on `asyncio.sleep` timing** (generic rule 16). To
   wait for an effect, poll the observable condition with a bounded timeout that raises on expiry —
   an `asyncio.wait_for` around a short poll loop, or a shared `wait_for`-style helper — not
   `await asyncio.sleep(<guess>)`. To exercise time-dependent behavior — a debounce window, a retry
   backoff — advance a controlled clock or drive the timer deterministically rather than shrinking
   the real interval and racing a real `asyncio.sleep` against it. A test whose result depends on
   which of two real-time intervals wins under `pytest-xdist -n auto` worker contention is flaky by
   construction; fix the synchronization, never widen the margin.

## Rationale

- Python has no compiler to enforce unit-level correctness, so an agent-authored unit test grades its
  own code and drifts to green-theater. The generic policy's behavioral model applies in full; this
  snippet only fixes the Python idioms that realize it.

## Scope

- All Python code in this repository and in projects managed by this platform.

## Enforcement

- The functional-versus-unit structure is enforced at review against `software-development/concept/functional-test-boundary`.
- Binding state — bound / unbound / duplicate / orphan — is measured against the scenario inventory; binding completeness is upheld at review.
- A test that gates correctness on `asyncio.sleep` timing — a guessed delay, or a shrunk timeout raced against a real emit — is rejected at review; the remedy is condition polling or a controlled clock.

## Exceptions

- None. There is no sanctioned unit test in Python.
