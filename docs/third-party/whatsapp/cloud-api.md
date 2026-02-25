# WhatsApp Business Cloud API

## Purpose

Direct integration with WhatsApp via Meta's hosted infrastructure. Use for high-volume customer messaging without third-party BSP (Twilio) markups.

## Core Concepts

- **WABA (WhatsApp Business Account)**: Root container for phone numbers and templates.
- **Phone Number ID**: Used in API endpoints (`/{phone_number_id}/messages`).
- **Webhook**: HTTPS POST endpoint for receiving messages and status updates.
- **24-Hour Window**: Customer-initiated messages open a 24h service window. Business replies are free (Service Conversations). Outside the window, only pre-approved template messages are allowed.
- **Graph API Versioning**: Base URL is `https://graph.facebook.com/{api_version}/`. Versions follow `vNN.0` format (e.g., `v21.0`, `v24.0`). Each version supported ~2 years. v20.0 expired May 2025; pin to v21.0+. Current latest: v24.0.

## API Authentication

All requests require `Authorization: Bearer {ACCESS_TOKEN}` header. Tokens are generated in Meta Business Manager or via System User tokens for production.

## Constraints

- Text body max: 4096 characters.
- Caption max: 1024 characters.
- Media max: 16MB for most types (100MB for video).
- Phone numbers must be in E.164 format (no `+` prefix in API calls).
- Phone numbers must be verified in Meta Business Manager.
- No message editing or deletion support.
- `messaging_product: "whatsapp"` is required in every request body.

## Sources

- [WhatsApp Business Platform](https://developers.facebook.com/docs/whatsapp)
- [Cloud API Reference](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [Webhook Payload Examples](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples)
- [Error Codes](https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes)
