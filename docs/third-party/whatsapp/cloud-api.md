# WhatsApp Business Cloud API

## Purpose

Direct integration with WhatsApp via Meta's hosted infrastructure. Use for high-volume customer messaging without third-party BSP (Twilio) markups.

## Core Concepts

- **WABA (WhatsApp Business Account)**: The root container for phone numbers and templates.
- **Phone Number ID**: Used in API endpoints to send messages.
- **Webhook**: HTTPS POST endpoint for receiving messages and status updates.
- **24-Hour Window**: Customer-initiated messages open a 24-hour service window. Business replies are free (Service Conversations) within this window.

## API Usage

### Sending a Message

```bash
POST /v20.0/<PHONE_NUMBER_ID>/messages
{
  "messaging_product": "whatsapp",
  "to": "<PHONE_NUMBER>",
  "type": "text",
  "text": { "body": "Hello from TeleClaude!" }
}
```

## Constraints

- **Message Content**: Template-only for business-initiated messages outside the 24h window.
- **Media**: Max 16MB for most media types.
- **Identity**: Phone numbers must be verified in Meta Business Manager.

## Gaps/Unknowns

- Meta's 2026 AI compliance rules for automated chatbots.
- Local payment integration specifics for "Conversational Commerce."

## Sources

- [Meta for Developers - WhatsApp Business Platform](https://developers.facebook.com/docs/whatsapp)
