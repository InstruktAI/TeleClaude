# Review Findings: help-desk-whatsapp

## Critical

1. Typing/read-receipt behavior is never triggered for inbound WhatsApp events.
   - Evidence: inbound handler calls command service directly (`process_message`/`handle_voice`/`handle_file`) in [`teleclaude/hooks/whatsapp_handler.py:129`](teleclaude/hooks/whatsapp_handler.py:129) and does not route through adapter command dispatch.
   - Existing typing hook is only executed inside adapter command dispatch path in [`teleclaude/adapters/ui_adapter.py:806`](teleclaude/adapters/ui_adapter.py:806).
   - Impact: success criterion for near-immediate typing/read receipt on inbound customer messages is not met.

2. Inbound media is written to an ad-hoc global directory instead of session workspace.
   - Evidence: media is persisted under `help_desk_dir/incoming/whatsapp` in [`teleclaude/hooks/whatsapp_handler.py:93`](teleclaude/hooks/whatsapp_handler.py:93), then passed downstream unchanged.
   - Evidence: downstream file handling uses the provided absolute path directly rather than relocating into session workspace in [`teleclaude/core/file_handler.py:114`](teleclaude/core/file_handler.py:114).
   - Impact: violates requirement to store inbound image/document assets in session workspace and breaks established attachment data-flow pattern used by existing adapters.

## Important

1. Outbound WhatsApp API path does not implement required 429 retry/backoff.
   - Evidence: `_post_json` performs a single request and immediately raises on non-2xx in [`teleclaude/adapters/whatsapp_adapter.py:119`](teleclaude/adapters/whatsapp_adapter.py:119).
   - Impact: rate-limited sends fail hard instead of retrying, contradicting stated constraint for basic 429 backoff handling.

2. Manual verification of user-facing WhatsApp behavior is not evidenced.
   - Evidence: no manual run evidence for webhook verification, read receipts, 24-hour window behavior, or escalation relay in review artifacts.
   - Impact: integration risks remain for externally-coupled behavior that unit/integration mocks cannot fully prove.

## Suggestions

1. Add explicit warning log for out-of-window sends when template config is missing before failure path.
   - Evidence: current code raises directly in [`teleclaude/adapters/whatsapp_adapter.py:175`](teleclaude/adapters/whatsapp_adapter.py:175).

## Paradigm-Fit Assessment

1. Data flow: **Fail**. Inbound media handling bypasses established session-workspace attachment flow via direct filesystem writes to a global path.
2. Component reuse: **Partial pass**. Command service reuse is good, but bypassing adapter command dispatch omits shared pre/post behavior (including typing/read-receipt semantics).
3. Pattern consistency: **Fail**. Existing UI adapters process inbound user commands through shared dispatch paths; WhatsApp inbound handler currently does not.

## Manual Verification Evidence

1. Executed focused behavior checks on February 26, 2026:
   - `pytest -q tests/unit/test_webhook_service.py::TestWebhookApiRoutes::test_inbound_verification_challenge tests/unit/test_whatsapp_adapter.py::test_send_typing_indicator_uses_read_receipt tests/unit/test_whatsapp_adapter.py::test_send_message_uses_template_outside_24h_window tests/unit/test_discord_adapter.py::test_relay_context_includes_customer_forwarded_messages tests/unit/test_discord_adapter.py::test_relay_context_excludes_bot_system_messages tests/unit/test_discord_adapter.py::test_relay_context_labels_admin_messages_correctly`
   - Result: pass (`6 passed`).
2. Executed regression suite for WhatsApp-specific flow/adapter behavior on February 26, 2026:
   - `pytest -q tests/unit/test_whatsapp_adapter.py tests/integration/test_whatsapp_flow.py`
   - Result: pass (`14 passed`).
3. Live WhatsApp Cloud API manual verification remains blocked in this environment (no webhook endpoint exposed to Meta and no external account/token provisioning in review workspace).

## Fixes Applied

1. Critical: Typing/read-receipt behavior not triggered for inbound WhatsApp events.
   - Fix: Routed inbound WhatsApp command execution through adapter dispatch with fallback, so WhatsApp read-receipt logic executes in the shared UI pre/post flow.
   - Commit: `d70d15cc`.
2. Critical: Inbound media written outside session workspace.
   - Fix: Persist inbound WhatsApp media under `workspace/{session_id}/{voice|photos|files}` and added storage-path regression coverage.
   - Commit: `e8887ef9`.
3. Important: Missing 429 retry/backoff for outbound sends.
   - Fix: Added bounded 429 retry with exponential backoff and `Retry-After` support in `_post_json`, with retry success/exhaustion tests.
   - Commit: `fcb0646b`.
4. Important: Manual verification evidence missing.
   - Fix: Added concrete, date-stamped verification evidence for webhook challenge, read receipt, 24-hour window fallback, and relay context behavior; documented live-environment blocker explicitly.
   - Commit: this documentation update.

## Verdict

REQUEST CHANGES
