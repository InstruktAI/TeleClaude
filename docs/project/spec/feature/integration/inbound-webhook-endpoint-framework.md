---
description: 'Dynamic route registration for external inbound webhooks — provider-specific path + verification config + normalizer key, mounted at runtime from teleclaude.yml.'
visibility: 'public'
---

# Inbound Webhook Endpoint Framework — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A pluggable inbound webhook framework that lets a provider's POST
endpoint be declared in `teleclaude.yml` (under
`hooks.inbound.<source_name>`) without writing new HTTP handler code.
On integration service startup, the hooks config loader reads the
inbound section and, for each entry, registers a verification handler
(for verification challenges) and a delivery handler (for the webhook
payload) on the inbound endpoint surface.

The delivery handler verifies the request signature when a `secret` is
configured, parses the body, looks up the registered normalizer by key,
invokes it to produce a hook event (or a list of events), and forwards
each event to the hook dispatcher. The verification handler implements
the WhatsApp / Meta verification challenge protocol when a
`verify_token` is configured.

## Canonical fields

### Use cases

#### UC-IF1: Config-driven registration

```gherkin
Given teleclaude.yml contains:
    hooks:
      inbound:
        whatsapp:
          path: /hooks/whatsapp
          normalizer: whatsapp
          verify_token: <token>
          secret: <hmac-secret>
When the integration service starts up and the hooks config loader processes the inbound section
Then the inbound-registration resolver extracts path, normalizer key, and verification config
And the inbound endpoint registry mounts the verification and delivery handlers
And both registrations are recorded
And an INFO log "registered inbound endpoint: /hooks/whatsapp (normalizer=whatsapp)" is emitted
```

#### UC-IF2: Path defaulted from source name

```gherkin
Given a hooks.inbound entry omits the path field
When the inbound-registration resolver runs
Then the path defaults to /hooks/inbound/<source_name>
And an INFO log records the derived path
```

#### UC-IF3: Verification challenge handshake (WhatsApp / Meta)

```gherkin
Given the inbound entry has verify_token = "abc123"
And an external provider issues a verification challenge with mode=subscribe, verify_token=abc123, challenge=xyz
When the verification handler runs
Then it checks mode == "subscribe", token matches verify_token, challenge is present
And echoes the challenge value as plain text in the accepted response
And NO hook event is created, NO dispatch happens
```

#### UC-IF4: Verification challenge rejected

```gherkin
Given a verification challenge arrives without the correct verify_token, or with a missing mode
When the verification handler evaluates the parameters
Then it rejects the challenge as forbidden
```

#### UC-IF5: Verification on non-verification endpoint is unsupported

```gherkin
Given the inbound entry has no verify_token set
When any verification request arrives at the registered path
Then the verification handler rejects it as method-not-supported
```

#### UC-IF6: HMAC signature verification

```gherkin
Given the inbound entry has secret = "shared-key" and the path is /hooks/github
And a delivery arrives carrying a signature header "sha256=<expected>"
When the delivery handler processes the request
Then it reads the raw body bytes
And computes an HMAC-SHA256 digest of the body under the shared secret
And compares against the signature header using a constant-time check
And on match: proceeds to normalization
And on mismatch: rejects the delivery as unauthorized
And on missing header (with secret configured): rejects the delivery as unauthorized
```

#### UC-IF7: Non-string secret rejected as misconfiguration

```gherkin
Given the verification config's secret is non-string (misconfiguration, e.g., a structured value)
When the delivery handler evaluates the secret
Then a warning "ignoring non-string secret config for inbound webhook" is logged
And the delivery is rejected as an internal misconfiguration
```

#### UC-IF8: Invalid body returns a client error

```gherkin
Given a delivery arrives with a body that does not parse as a structured payload
When the delivery handler runs the parser
Then the delivery is rejected with an "invalid payload" client error
And the exception is logged
```

#### UC-IF9: Missing normalizer is an internal error

```gherkin
Given the normalizer key is not registered in the normalizer registry
When the delivery handler looks up the normalizer
Then the delivery is rejected with a "normalizer not configured" internal error
And the error is logged
```

#### UC-IF10: Normalizer raising → client error

```gherkin
Given the normalizer raises an exception while parsing
When the delivery handler invokes the normalizer
Then the exception is caught
And the delivery is rejected with a "failed to normalize payload" client error chained with the original exception
```

#### UC-IF11: Dispatch escape vs swallowed handler failures

```gherkin
Given normalization succeeded and produced one or more hook events
And the dispatcher internally catches per-contract handler exceptions and webhook-enqueue exceptions, logging them and continuing to the next match
When dispatch returns normally (the common case, even when individual handlers raised inside)
Then the delivery handler returns an accepted response
And the provider sees a successful delivery (no retry)

Given an exception ESCAPES the dispatcher itself (e.g., the matcher faults, the contract iteration crashes, or a downstream component raises outside the per-contract guard)
When dispatch raises
Then the delivery handler's outer guard catches the exception
And the delivery is rejected with a transient upstream-failure status
And the provider (WhatsApp, GitHub) interprets the transient status as retry-eligible

In v1 practice, handler exceptions do NOT trigger a retry-eligible
rejection — they are absorbed by dispatch. Operators inspecting
"missing" inbound events must check error logs for the per-contract
"internal handler failed" entries.
```

#### UC-IF12: Multi-event normalizer

```gherkin
Given a normalizer returns a list of hook events (e.g., WhatsApp may carry multiple messages in one webhook)
When the delivery handler processes the normalized result
Then it iterates and dispatches every event in order
And returns an accepted response on completion
```

#### UC-IF13: Duplicate path registration is ignored

```gherkin
Given the inbound endpoint registry has already registered a path
When a second registration call arrives for the same path
Then a warning "inbound path already registered" is logged
And the function returns without re-mounting handlers
```

#### UC-IF14: Normalizer signature compatibility

```gherkin
Given a normalizer's signature accepts only (payload) — the legacy form
When the normalizer-invoke helper inspects the signature
Then it detects the lack of headers support
And invokes the normalizer with payload only
Given a normalizer accepts (payload, headers) or variadic args
When the same invocation runs
Then the normalizer is called with both arguments
```

### Cross-context references

- This is the canonical inbound boundary for the `integration` context.
- The dispatch callback wires through `eventbus-hook-bridge`'s
  hook dispatcher to the contract registry's matcher.
- Built-in normalizers consumed: `github-webhook-normalization` and
  `whatsapp-inbound-conversation-routing` register their normalizers
  here.
- Verification posture is the v1 implementation of the v2 domain spec's
  "fail-closed allowlist" + "webhook authentication is provider-specific"
  rules.

## Known caveats

- In default v1 production configs, the `hooks.inbound` section is empty
  — no inbound endpoints are registered from YAML. The framework is
  wired and exercised by test suites and by deployment configurations
  that populate `hooks.inbound` (e.g., help-desk WhatsApp deployments).
  Production observability for the framework therefore comes from
  configuration-driven activation, not from baseline service startup.
- HMAC signature verification accepts EITHER `X-Hub-Signature-256`
  (GitHub-style) OR `X-Hook-Signature` (TeleClaude internal contract
  delivery format). The same handler serves both naming conventions.
- The verification challenge handler is hard-coded to the Meta /
  WhatsApp subscribe protocol; other providers requiring different
  challenge handshakes would need code changes, not config.
- The framework does NOT enforce an allowlist on event NAMES — only on
  path mounting. Any event the normalizer produces is forwarded to the
  dispatcher; allowlist enforcement is a contract-level concern in v1.
- A retry-eligible rejection invites provider retries; the dispatcher
  itself does NOT implement provider-side dedupe — duplicate deliveries
  from retried providers will produce duplicate hook events.
- The framework mounts handlers on whichever inbound endpoint surface
  the integration service exposes at startup; if the inbound surface
  is not available at startup, inbound registration is skipped with a
  warning and inbound endpoints remain inactive until restart.
