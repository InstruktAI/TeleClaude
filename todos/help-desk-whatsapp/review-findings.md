# Review Findings: help-desk-whatsapp

## Critical

None.

## Important

1. WhatsApp inbound session creation does not honor the configured help-desk workspace. (confidence: 95)
   - Evidence: inbound flow explicitly requests `config.computer.help_desk_dir` when creating a new session in `teleclaude/hooks/whatsapp_handler.py:38`.
   - Evidence: `create_session` then forces all non-admin sessions into `os.path.join(WORKING_DIR, "help-desk")` in `teleclaude/core/command_handlers.py:326` and `teleclaude/core/command_handlers.py:332`.
   - Concrete trace: for a new WhatsApp sender, `human_role` resolves to `customer` (`teleclaude/core/identity.py:177`), so the forced jail branch always executes and discards the configured path.
   - Impact: violates the success criterion requiring new WhatsApp customer sessions to land in the configured help-desk workspace.

2. 429 retry/backoff is implemented for JSON sends but not for media upload calls. (confidence: 90)
   - Evidence: `_post_json` retries on 429 (`teleclaude/adapters/whatsapp_adapter.py:122`), but `_upload_media` performs a single POST and immediately raises on non-2xx (`teleclaude/adapters/whatsapp_adapter.py:270` and `teleclaude/adapters/whatsapp_adapter.py:276`).
   - Impact: `send_file()` can hard-fail under rate limiting, which contradicts the stated WhatsApp rate-limit constraint.

3. Live manual verification for user-facing WhatsApp behavior is still missing in this review round. (confidence: 100)
   - Evidence: only mocked/unit/integration tests were run in this environment; no external webhook callback/API-account validation was possible.
   - Impact: provider-contract risks remain for verification challenge behavior, real delivery semantics, and out-of-window template behavior.

## Suggestions

1. Add a regression test that proves WhatsApp customer sessions preserve `config.computer.help_desk_dir` end-to-end.
2. Add `send_file` retry tests covering 429 on the media upload endpoint.

## Paradigm-Fit Assessment

1. Data flow: partial fail. The inbound handler chooses the configured help-desk path, but the core session-creation path rewrites it to a different transport-agnostic constant, breaking contract fidelity across the call chain.
2. Component reuse: pass. The feature reuses shared command service, UI dispatch flow, and metadata patterns consistently.
3. Pattern consistency: pass with caveat. WhatsApp follows adapter/normalizer registration patterns, but path rewriting introduces cross-layer policy inconsistency.

## Manual Verification Evidence

1. Executed on February 26, 2026:
   - `pytest -q tests/unit/test_whatsapp_adapter.py tests/integration/test_whatsapp_flow.py tests/unit/test_identity.py tests/unit/test_config_schema.py`
   - Result: pass (`54 passed`).
2. Executed on February 26, 2026:
   - `pytest -q tests/unit/test_agent_coordinator.py tests/unit/test_discord_adapter.py`
   - Result: pass (`81 passed`).
3. Executed on February 26, 2026:
   - `ruff check teleclaude/adapters/whatsapp_adapter.py teleclaude/hooks/whatsapp_handler.py teleclaude/hooks/normalizers/whatsapp.py tests/unit/test_whatsapp_adapter.py tests/integration/test_whatsapp_flow.py`
   - Result: pass.
4. Executed on February 26, 2026:
   - `pyright teleclaude/adapters/whatsapp_adapter.py teleclaude/hooks/whatsapp_handler.py teleclaude/hooks/normalizers/whatsapp.py teleclaude/core/identity.py teleclaude/core/models.py`
   - Result: pass (`0 errors`).
5. Live WhatsApp Cloud API verification is blocked in this environment (no externally reachable webhook endpoint and no provisioned account/token pair for end-to-end calls).
6. Executed on February 26, 2026:
   - `pytest -q tests/unit/test_access_control.py tests/unit/test_whatsapp_adapter.py tests/integration/test_whatsapp_flow.py`
   - Result: pass (`22 passed`).
7. Executed on February 26, 2026:
   - `ruff check teleclaude/adapters/whatsapp_adapter.py teleclaude/hooks/whatsapp_handler.py teleclaude/core/command_handlers.py tests/unit/test_access_control.py tests/unit/test_whatsapp_adapter.py tests/integration/test_whatsapp_flow.py`
   - Result: pass.

## Fixes Applied

1. Important #1 (configured help-desk workspace ignored)
   - Fix: non-admin jailing in `create_session` now uses configured `config.computer.help_desk_dir` (with existing fallback), and regression coverage was added in `tests/unit/test_access_control.py`.
   - Commit: `1b89d167`
2. Important #2 (media upload missing 429 retries)
   - Fix: `_upload_media` now retries 429 responses with `Retry-After`/exponential backoff parity, and regression tests were added for retry success and retry exhaustion in `tests/unit/test_whatsapp_adapter.py`.
   - Commit: `a12be752`
3. Important #3 (live manual WhatsApp verification missing)
   - Status: blocked in this environment; no externally reachable webhook endpoint and no provisioned WhatsApp Cloud API account/token pair were available to execute live callback/delivery verification.
   - Clarification: revalidated on February 26, 2026 by checking runtime environment/config prerequisites; WhatsApp Cloud credentials and a publicly reachable webhook target remain unavailable in this workspace.
   - Commit: `14eaf257` (documentation-only blocker clarification; no product code change)

## Verdict

REQUEST CHANGES
