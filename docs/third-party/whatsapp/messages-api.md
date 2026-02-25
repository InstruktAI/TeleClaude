# WhatsApp Messages API

## Purpose

Reference for sending messages (text, media, templates) and marking messages as read via the WhatsApp Cloud API.

## Endpoint

```
POST https://graph.facebook.com/{api_version}/{phone_number_id}/messages
Authorization: Bearer {ACCESS_TOKEN}
Content-Type: application/json
```

## Send Text Message

```json
{
  "messaging_product": "whatsapp",
  "to": "15551234567",
  "type": "text",
  "text": { "body": "Hello from TeleClaude!" }
}
```

**Response:**

```json
{
  "messaging_product": "whatsapp",
  "contacts": [{ "input": "15551234567", "wa_id": "15551234567" }],
  "messages": [{ "id": "wamid.HBgN..." }]
}
```

The `wamid` is the message ID used for read receipts and tracking.

## Send Media Messages

Media can be sent by uploaded `id` or by public `link`. Use `id` for uploaded media, `link` for publicly accessible URLs.

### Image

```json
{
  "messaging_product": "whatsapp",
  "to": "15551234567",
  "type": "image",
  "image": { "id": "MEDIA_ID", "caption": "Optional caption (max 1024 chars)" }
}
```

Or by link: `"image": { "link": "https://example.com/image.jpg", "caption": "..." }`

### Document

```json
{
  "messaging_product": "whatsapp",
  "to": "15551234567",
  "type": "document",
  "document": { "id": "MEDIA_ID", "caption": "Optional", "filename": "report.pdf" }
}
```

### Audio

```json
{
  "messaging_product": "whatsapp",
  "to": "15551234567",
  "type": "audio",
  "audio": { "id": "MEDIA_ID" }
}
```

Audio does not support captions.

### Video

```json
{
  "messaging_product": "whatsapp",
  "to": "15551234567",
  "type": "video",
  "video": { "id": "MEDIA_ID", "caption": "Optional" }
}
```

## Send Template Message

Used for out-of-24h-window messaging. Templates must be pre-approved in WhatsApp Business Manager.

```json
{
  "messaging_product": "whatsapp",
  "to": "15551234567",
  "type": "template",
  "template": {
    "name": "hello_world",
    "language": { "code": "en_US" },
    "components": [
      {
        "type": "body",
        "parameters": [{ "type": "text", "text": "John" }]
      }
    ]
  }
}
```

### Template Components

- `type`: `header`, `body`, `button`
- `sub_type` (for buttons): `quick_reply`, `url`, `catalog`
- `parameters`: Array of `{ "type": "text", "text": "value" }` objects
- `index` (for buttons): 0-9 position index
- Language `code`: supports `language` and `language_locale` formats (e.g., `en`, `en_US`)
- Language `policy`: must be `deterministic`

## Mark Message as Read

Send to the same messages endpoint with `status` field:

```json
{
  "messaging_product": "whatsapp",
  "status": "read",
  "message_id": "wamid.HBgN..."
}
```

This marks the message as read (blue ticks) in the customer's WhatsApp. Used as the typing indicator equivalent.

## Reply to a Message (Context)

Include `context` with the message ID being replied to:

```json
{
  "messaging_product": "whatsapp",
  "to": "15551234567",
  "type": "text",
  "context": { "message_id": "wamid.ORIGINAL_MESSAGE_ID" },
  "text": { "body": "This is a reply" }
}
```

## Message Limits

- Text body: 4096 characters max
- Caption (image/document/video): 1024 characters max
- `biz_opaque_callback_data`: 512 characters max (optional tracking string)
- No message editing support
- No message deletion support

## Sources

- [Cloud API Messages Reference](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages)
- [Send Messages Guide](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages)
- [Template Messages](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates)
