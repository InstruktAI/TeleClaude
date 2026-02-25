# WhatsApp Webhooks

## Purpose

Reference for receiving inbound messages and status updates via WhatsApp Cloud API webhooks.

## Webhook Verification Challenge

When configuring the webhook URL in Meta App Dashboard, Meta sends a GET request to verify ownership:

```
GET {callback_url}?hub.mode=subscribe&hub.verify_token={your_token}&hub.challenge={challenge_string}
```

Your endpoint must:

1. Check `hub.mode` is `subscribe`
2. Check `hub.verify_token` matches your configured token
3. Return `hub.challenge` as the response body with 200 status

## Signature Verification

Every POST webhook delivery includes an `X-Hub-Signature-256` header containing an HMAC-SHA256 signature:

```
X-Hub-Signature-256: sha256={hmac_hex_digest}
```

Verify by computing HMAC-SHA256 of the raw request body using your app secret as the key. Compare with the header value.

```python
import hmac, hashlib

def verify_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    expected = hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

## Webhook Payload Structure

All webhook payloads follow this nested structure:

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "display_phone_number": "BUSINESS_PHONE",
          "phone_number_id": "PHONE_NUMBER_ID"
        },
        "contacts": [{ "profile": { "name": "NAME" }, "wa_id": "SENDER_WA_ID" }],
        "messages": [{ ... }],
        "statuses": [{ ... }]
      },
      "field": "messages"
    }]
  }]
}
```

Key path: `entry[].changes[].value` — contains either `messages` (inbound) or `statuses` (delivery updates).

## Inbound Message Types

### Text Message

```json
{
  "from": "SENDER_PHONE",
  "id": "wamid.ID",
  "timestamp": "UNIX_TIMESTAMP",
  "type": "text",
  "text": { "body": "MESSAGE_TEXT" }
}
```

### Image Message

```json
{
  "from": "SENDER_PHONE",
  "id": "wamid.ID",
  "timestamp": "UNIX_TIMESTAMP",
  "type": "image",
  "image": {
    "caption": "CAPTION",
    "mime_type": "image/jpeg",
    "sha256": "HASH",
    "id": "MEDIA_ID"
  }
}
```

### Document Message

```json
{
  "from": "SENDER_PHONE",
  "id": "wamid.ID",
  "timestamp": "UNIX_TIMESTAMP",
  "type": "document",
  "document": {
    "caption": "CAPTION",
    "filename": "file.pdf",
    "mime_type": "application/pdf",
    "sha256": "HASH",
    "id": "MEDIA_ID"
  }
}
```

### Audio/Voice Message

```json
{
  "from": "SENDER_PHONE",
  "id": "wamid.ID",
  "timestamp": "UNIX_TIMESTAMP",
  "type": "audio",
  "audio": {
    "mime_type": "audio/ogg; codecs=opus",
    "sha256": "HASH",
    "id": "MEDIA_ID",
    "voice": true
  }
}
```

Voice notes arrive as `type: "audio"` with MIME type `audio/ogg; codecs=opus` and `"voice": true`. Regular audio files omit the `voice` field. Use this to distinguish voice notes for Whisper transcription.

### Video Message

```json
{
  "from": "SENDER_PHONE",
  "id": "wamid.ID",
  "timestamp": "UNIX_TIMESTAMP",
  "type": "video",
  "video": {
    "mime_type": "video/mp4",
    "sha256": "HASH",
    "id": "MEDIA_ID"
  }
}
```

### Sticker Message

```json
{
  "type": "sticker",
  "sticker": {
    "mime_type": "image/webp",
    "sha256": "HASH",
    "id": "MEDIA_ID"
  }
}
```

### Unknown/Unsupported Type

```json
{
  "type": "unknown",
  "errors": [
    {
      "code": 131051,
      "details": "Message type is not currently supported",
      "title": "Unsupported message type"
    }
  ]
}
```

## Status Update Webhooks

Status updates appear in `value.statuses[]` (not `value.messages[]`):

### Sent/Delivered/Read

```json
{
  "id": "wamid.MESSAGE_ID",
  "status": "sent",
  "timestamp": "UNIX_TIMESTAMP",
  "recipient_id": "RECIPIENT_WA_ID",
  "conversation": {
    "id": "CONVERSATION_ID",
    "expiration_timestamp": "EXPIRY_TIMESTAMP",
    "origin": { "type": "CATEGORY" }
  },
  "pricing": {
    "billable": true,
    "pricing_model": "CBP",
    "category": "CATEGORY"
  }
}
```

Status values: `sent`, `delivered`, `read`, `failed`.

### Failed Status

Includes `errors` array:

```json
{
  "status": "failed",
  "errors": [
    {
      "code": 131050,
      "title": "Unable to deliver the message...",
      "message": "ERROR_MESSAGE",
      "error_data": { "details": "ERROR_DETAILS" },
      "href": "https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/"
    }
  ]
}
```

## Webhook Fields

Subscribe to the `messages` field in Meta App Dashboard to receive both message and status notifications.

## Sources

- [Webhook Payload Examples](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples)
- [Webhook Components](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components)
- [Create Webhook Endpoint](https://developers.facebook.com/docs/whatsapp/webhooks/create-webhook-endpoint)
