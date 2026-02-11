# Review Findings: tts-fallback-saturation

## Review Round 1

### Requirements Tracing

| Requirement                                   | Implementation                               | Status |
| --------------------------------------------- | -------------------------------------------- | ------ |
| `trigger_event` queries `voices_in_use`       | `manager.py:209`                             | ✅     |
| Fallback chain filters `service_cfg.voices`   | `manager.py:227`                             | ✅     |
| Saturated providers skipped                   | `manager.py:228-230`                         | ✅     |
| No blind `random.choice()` on full voice list | `manager.py:231` (on `available` only)       | ✅     |
| `create_session` no longer assigns a voice    | `command_handlers.py` import + block removed | ✅     |
| Voiceless services use sentinel               | `manager.py:233-237`                         | ✅     |
| Primary voice always first                    | `manager.py:206` + line 219 skip             | ✅     |
| Lazy voice assignment                         | `manager.py:197` via `_get_or_assign_voice`  | ✅     |

### Critical

(none)

### Important

(none)

### Suggestions

1. **Double `get_voices_in_use` query for new sessions** — `manager.py:209` + `manager.py:73` (inside `get_random_voice_for_session`, called by `_get_or_assign_voice` for first-time assignment). When a session has no voice yet, `get_voices_in_use` is called twice: once during lazy assignment and once for fallback filtering. Low impact (one extra DB query on first TTS event only), but could be optimized by passing the result through.

2. **Test: `_get_or_assign_voice` lazy assignment branch untested** — `test_tts_fallback_saturation.py:91` always mocks `db.get_voice` to return a pre-set voice. The "no voice exists" branch (lines 128-140) is exercised only indirectly. Adding a test where `db.get_voice` returns `None` would cover the full lazy path.

3. **Test: no negative assertion on `create_session`** — The removal of `get_random_voice` mocks from `test_command_handlers.py` proves the code doesn't need them, but no test explicitly asserts that voice assignment doesn't happen during `create_session`. Adding a mock-that-raises would guard against reintroduction.

4. **Test: dead `captured_chains` in `_trigger` helper** — `test_tts_fallback_saturation.py:77-81`: `_capture_tts` body never executes because the coroutine is `.close()`'d by the mocked `asyncio.create_task`. The test correctly reads from `mock_run.mock_calls` instead. The `side_effect` could be simplified to `AsyncMock()`.

5. **`speak()` method not updated** — `manager.py:276` still uses bare `random.choice(service_cfg.voices)` without saturation filtering. This is correct (sessionless, no "one voice per session" invariant applies), but noting for awareness.

## Verdict: APPROVE
