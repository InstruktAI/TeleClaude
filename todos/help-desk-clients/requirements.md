# Help Desk Clients — Requirements

## Goal

Connect external messaging platforms (WhatsApp, Discord) to the Help Desk lobby and establish the "Admin Supergroup" observability model. This todo focuses on the adapter layer and unified streaming.

## Research Input (Required)

- `docs/third-party/assistant-ui/index.md` — Reference for token design and Web integration patterns.
- _Note: Specific WhatsApp/Discord API docs are pending creation in docs/third-party/._

## Core Requirements

1.  **WhatsApp Adapter**
    - Integrate WhatsApp Business API (via Twilio or similar provider).
    - Map phone numbers to `IdentityContext` (Role: Customer).
    - Route ingress to `help-desk` project via `create_session`.

2.  **Discord Adapter**
    - Integrate Discord Bot API.
    - Map Discord User IDs to `IdentityContext` (Role: Customer).
    - Route ingress to `help-desk` project.

3.  **Admin Observability (The Control Room)**
    - **Supergroup Logic:** Extend the Telegram Adapter's "Forum Topic" model to include _all_ Help Desk sessions, not just those created by the Admin.
    - **Stream Mirroring:** When a customer starts a session in `help-desk`, the `agent-activity-events` layer must mirror activity events to a new topic in the Admin Telegram Supergroup.
    - **Intervention:** Allow Admins to send messages _into_ that customer session from the Telegram topic (using the mirrored `session_id`).

4.  **Unified Streaming**
    - Leverage `agent-activity-events` infrastructure.
    - Ensure `AdapterClient` routes output to _both_ the origin adapter (WhatsApp/Discord) AND the Admin Telegram adapter (if configured as supervisor).

## Success Criteria

- A WhatsApp message spawns a jailed session in `help-desk`.
- That session appears as a new topic in the Admin Telegram Group.
- The Admin can reply in Telegram, and the text appears in the WhatsApp chat.
- The Customer (WhatsApp) only sees the AI response, not the Admin's internal notes (unless explicitly sent as reply).
