---
description: How GitHub signs webhook deliveries and how a receiver validates them.
---

# GitHub Webhook Delivery Validation

## Signature

- GitHub signs a delivery only when the webhook has a secret configured. Without
  a secret, the `X-Hub-Signature-256` header is absent.
- The `X-Hub-Signature-256` header carries `sha256=<hex digest>`: an HMAC-SHA256
  hex digest of the raw payload body, keyed with the webhook's secret.
- The `X-Hub-Signature` header carries an HMAC-SHA1 signature and is included
  only for legacy purposes.

## Validation

- Compute the HMAC-SHA256 of the payload exactly as received, under the same
  secret, and compare it with the header value.
- Handle the payload as UTF-8, because payloads can contain unicode characters.
- Compare with a constant-time comparison, never a plain equality operator, to
  avoid timing attacks.
- A proxy or load balancer in front of the receiver must not modify the payload
  or the headers, or validation fails.

## Sources

- [Validating webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
