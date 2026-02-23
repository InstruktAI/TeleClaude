# WhatsApp Rate Limits & Error Codes

## Purpose

Reference for rate limiting, messaging tiers, error handling, and API versioning in the WhatsApp Cloud API.

## Messaging Tiers

Business accounts start at the lowest tier and upgrade based on message quality and volume:

| Tier       | Messages / 24h | How to Reach                                            |
| ---------- | -------------- | ------------------------------------------------------- |
| Unverified | 250            | New account default                                     |
| Tier 1     | 1,000          | Verify business                                         |
| Tier 2     | 10,000         | Send 2x current limit in 7 days with acceptable quality |
| Tier 3     | 100,000        | Send 2x current limit in 7 days with acceptable quality |
| Unlimited  | No limit       | Maintain high quality rating                            |

Tier limits apply to unique customers contacted per 24h rolling window, not total messages.

## API Rate Limits

- **Messages endpoint**: 80 messages/second per phone number (Cloud API).
- **Media upload**: 1,000 requests/day per phone number.
- **Business Management API**: Standard Graph API rate limits apply (200 calls/user/hour).
- When exceeded, returns HTTP 429 with `error.code: 130429`.

## Conversation-Based Pricing

| Category       | Trigger                           | Window                     |
| -------------- | --------------------------------- | -------------------------- |
| Service        | Customer sends first message      | 24h from customer message  |
| Marketing      | Business sends marketing template | 24h from template delivery |
| Utility        | Business sends utility template   | 24h from template delivery |
| Authentication | Business sends auth template      | 24h from template delivery |

Service conversations (customer-initiated) have different pricing than business-initiated.

## Common Error Codes

### HTTP Status Codes

| HTTP | Meaning                          |
| ---- | -------------------------------- |
| 200  | Success                          |
| 400  | Bad request (invalid payload)    |
| 401  | Unauthorized (bad/expired token) |
| 404  | Endpoint or resource not found   |
| 429  | Rate limit exceeded              |
| 500  | Internal server error            |

### WhatsApp-Specific Error Codes (131xxx)

| Code   | Title                          | Action                              |
| ------ | ------------------------------ | ----------------------------------- |
| 130429 | Rate limit hit                 | Retry with exponential backoff      |
| 131000 | Something went wrong           | Retry; if persists, contact support |
| 131005 | Access denied                  | Check permissions and token         |
| 131008 | Required parameter missing     | Check payload structure             |
| 131009 | Parameter value invalid        | Check field types and formats       |
| 131016 | Service unavailable            | Retry with backoff                  |
| 131021 | Recipient not on WhatsApp      | Do not retry; invalid number        |
| 131026 | Message undeliverable          | Check recipient status              |
| 131047 | Re-engagement message required | 24h window expired; use template    |
| 131050 | User opted out of marketing    | Do not send marketing templates     |
| 131051 | Unsupported message type       | Check message type field            |
| 131053 | Media upload error             | Check file size and MIME type       |

### Error Response Format

```json
{
  "error": {
    "message": "Human-readable error description",
    "type": "OAuthException",
    "code": 100,
    "error_subcode": 2534015,
    "error_data": { "details": "Detailed error info" },
    "fbtrace_id": "TRACE_ID"
  }
}
```

For webhook status failures:

```json
{
  "errors": [
    {
      "code": 131050,
      "title": "Error title",
      "message": "Error message",
      "error_data": { "details": "Details" },
      "href": "https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/"
    }
  ]
}
```

## Retry Strategy

- **429 (rate limit)**: Exponential backoff starting at 1s, max 60s.
- **500/131000/131016**: Retry up to 3 times with backoff.
- **131021/131050**: Do not retry (permanent failures).
- **131047**: Switch to template message (24h window expired).

## API Versioning

- Base URL: `https://graph.facebook.com/{version}/`
- Version format: `vNN.0` (e.g., `v21.0`, `v24.0`)
- New versions release roughly every 3-4 months.
- Each version supported for ~2 years after release.
- Deprecation notices published in Meta changelog.
- Pin to a specific version; do not use unversioned endpoints.
- Breaking changes between versions are documented in the Graph API changelog.

### Version Timeline (as of Feb 2026)

| Version | Released | Available Until         |
| ------- | -------- | ----------------------- |
| v20.0   | May 2024 | **Expired May 6, 2025** |
| v21.0   | Oct 2024 | TBD                     |
| v22.0   | Jan 2025 | Feb 10, 2026            |
| v23.0   | May 2025 | Jun 9, 2026             |
| v24.0   | Oct 2025 | TBD (current latest)    |

Pin to **v21.0** or later. As of Sep 2025, Meta rejects requests to versions older than v22.0.

## Sources

- [Error Codes Reference](https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes)
- [Messaging Limits](https://developers.facebook.com/docs/whatsapp/messaging-limits)
- [Conversation-Based Pricing](https://developers.facebook.com/docs/whatsapp/pricing)
- [Graph API Versioning](https://developers.facebook.com/docs/graph-api/guides/versioning)
