# WhatsApp Media API

## Purpose

Reference for uploading, retrieving, and downloading media via the WhatsApp Cloud API.

## Upload Media

```
POST https://graph.facebook.com/{api_version}/{phone_number_id}/media
Authorization: Bearer {ACCESS_TOKEN}
Content-Type: multipart/form-data
```

Form fields:

- `file`: The media file binary
- `type`: MIME type (e.g., `image/jpeg`)
- `messaging_product`: `whatsapp`

**Response:**

```json
{ "id": "MEDIA_ID" }
```

The returned `MEDIA_ID` can be used in send message requests.

## Retrieve Media URL

```
GET https://graph.facebook.com/{api_version}/{media_id}
Authorization: Bearer {ACCESS_TOKEN}
```

**Response:**

```json
{
  "url": "https://lookaside.fbsbx.com/...",
  "mime_type": "image/jpeg",
  "sha256": "HASH",
  "file_size": 12345,
  "id": "MEDIA_ID",
  "messaging_product": "whatsapp"
}
```

## Download Media

Use the URL from the retrieval step. The download URL requires the same access token:

```
GET {url_from_retrieval}
Authorization: Bearer {ACCESS_TOKEN}
```

Returns the raw binary file. The download URL is on a different domain (`lookaside.fbsbx.com`), not `graph.facebook.com` — but the same Bearer token is required. This is the most common integration failure point.

The URL expires after approximately **5 minutes**. Always retrieve a fresh URL immediately before downloading.

## Supported Media Types and Limits

| Type     | MIME Types                                                                          | Max Size                           |
| -------- | ----------------------------------------------------------------------------------- | ---------------------------------- |
| Image    | image/jpeg, image/png                                                               | 5 MB                               |
| Document | application/pdf, application/vnd.ms-_, application/vnd.openxmlformats-_, text/plain | 100 MB                             |
| Audio    | audio/aac, audio/mp4, audio/mpeg, audio/amr, audio/ogg (Opus codec only)            | 16 MB                              |
| Video    | video/mp4, video/3gp                                                                | 16 MB                              |
| Sticker  | image/webp                                                                          | 100 KB (static), 500 KB (animated) |
| Voice    | audio/ogg; codecs=opus                                                              | 16 MB                              |

## Media ID Lifecycle

- Media IDs are valid for 30 days after upload.
- Media URLs from retrieval expire after ~5 minutes.
- Always retrieve fresh URLs immediately before downloading; never cache media URLs.

## Inbound Media Handling

When a customer sends media, the webhook payload includes a `media_id`. To download:

1. Call `GET /{media_id}` to get the temporary download URL
2. Download the file from the URL with the access token
3. The webhook payload also includes `mime_type` and `sha256` for validation

Example inbound image webhook data:

```json
{
  "type": "image",
  "image": {
    "caption": "CAPTION",
    "mime_type": "image/jpeg",
    "sha256": "IMAGE_HASH",
    "id": "MEDIA_ID"
  }
}
```

## Sources

- [Cloud API Media Reference](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media)
- [Send Media Messages Guide](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages#media-messages)
