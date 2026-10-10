---
description: How GitHub encodes and signs webhook deliveries, and how a receiver validates them.
---

# GitHub Webhook Delivery Validation

## Signature

- GitHub signs a delivery only when the webhook has a secret configured. Without
  a secret, the `X-Hub-Signature-256` header is absent.
- The `X-Hub-Signature-256` header carries `sha256=<hex digest>`: an HMAC-SHA256
  hex digest of the raw payload body, keyed with the webhook's secret.
- The `X-Hub-Signature` header carries an HMAC-SHA1 signature and is included
  only for legacy purposes.

## Content types

- A webhook's content type is `json` or `form`; the REST API documents `form` as
  the default.
- `json` sends the JSON payload unwrapped as the request body.
- `form` sends the request as `application/x-www-form-urlencoded`, with the JSON
  payload as the value of a single form parameter named `payload`.
- The signature covers the request body exactly as sent, so for `form` it covers
  the form-encoded body, not the JSON inside it. The documentation states only
  "the payload contents"; the TeleClaude ingress validates `form` deliveries
  over the raw form-encoded body.

## Validation

- Compute the HMAC-SHA256 of the payload exactly as received, under the same
  secret, and compare it with the header value.
- Handle the payload as UTF-8, because payloads can contain unicode characters.
- Compare with a constant-time comparison, never a plain equality operator, to
  avoid timing attacks.
- A proxy or load balancer in front of the receiver must not modify the payload
  or the headers, or validation fails.

## Sources

- [Creating webhooks](https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks)
- [REST API endpoints for repository webhooks](https://docs.github.com/en/rest/repos/webhooks)
- [Validating webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
