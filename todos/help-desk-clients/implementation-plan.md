# Help Desk Clients — Implementation Plan

## Phase 1: Adapter Foundation

Implement the new adapters using the `Adapter` base class and `person-identity-auth` logic.

- [ ] **WhatsApp Adapter:**
  - Scaffold `teleclaude/adapters/whatsapp_adapter.py`.
  - Implement `Twilio` webhook handler.
  - Map phone number -> Identity -> Session.
- [ ] **Discord Adapter:**
  - Scaffold `teleclaude/adapters/discord_adapter.py`.
  - Implement `discord.py` client.
  - Map User ID -> Identity -> Session.

## Phase 2: Admin Mirroring (Supergroup)

Update the Telegram adapter to subscribe to global session events.

- [ ] **Supervisor Mode:** Add config option `telegram.supervisor_group_id`.
- [ ] **Topic Creation:** When a session starts in `help-desk` (regardless of origin), the Telegram adapter creates a topic in `supervisor_group_id`.
- [ ] **Metadata Mapping:** Store the `session_id` in the topic description or local DB map to enable routing replies back to the session.

## Phase 3: Unified Routing

Update `AdapterClient` to support multi-destination delivery.

- [ ] **Fan-out Logic:** In `send_output_update`, check if the session is a `help-desk` session.
  - If yes -> Send to Origin Adapter (WhatsApp) AND Supervisor Adapter (Telegram).
- [ ] **Input Routing:** When Admin replies in the Supervisor topic, `TelegramAdapter` routes the message to the `session_id`.
  - **Logic:** Must distinguish "Talk to Agent" vs "Talk to User" (Future scope: for now, assume Admin input goes to the Agent context, visible to User via AI response, or direct injection if supported).

## Phase 4: Verification

- [ ] **End-to-End Test:**
  - Simulate WhatsApp ingress.
  - Verify Telegram topic creation.
  - Verify output streams to both.
  - Verify Admin input reaches the session.
