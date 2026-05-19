---
id: project/spec/feature/integration/inbound-webhook-endpoint-framework
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Dynamic FastAPI route registration for external inbound webhooks — provider-specific path + verification config + normalizer key, mounted at runtime from teleclaude.yml.
---

# Inbound Webhook Endpoint Framework — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A pluggable inbound webhook framework that lets a provider's POST endpoint
be declared in `teleclaude.yml` (under `hooks.inbound.<source_name>`)
without writing new HTTP handler code. On daemon startup,
`load_hooks_config` reads the inbound section and, for each entry, calls
`InboundEndpointRegistry.register(path, normalizer_key, verify_config)`
which mounts both a GET handler (for verification challenges) and a POST
handler (for the webhook payload) on the FastAPI app.

The POST handler verifies the request signature when a `secret` is
configured, parses the JSON body, looks up the registered normalizer by
key, invokes it to produce a `HookEvent` (or a list of events), and
forwards each event to the `HookDispatcher.dispatch` callback. The GET
handler implements the WhatsApp / Meta verification challenge protocol
when a `verify_token` is configured.

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
When the daemon starts up and load_hooks_config processes the inbound section
Then _resolve_inbound_registration extracts path, normalizer_key, verify_config
And InboundEndpointRegistry.register(path, normalizer_key, verify_config) is called
And both GET and POST routes are added to the FastAPI app with tags=["hooks-inbound"]
And the path is recorded in _registered_paths
And an INFO log "Registered inbound endpoint: /hooks/whatsapp (normalizer=whatsapp)" is emitted
```

#### UC-IF2: Path defaulted from source name

```gherkin
Given a hooks.inbound entry omits the path field
When _resolve_inbound_registration runs
Then path defaults to /hooks/inbound/<source_name>
And an INFO log records the derived path
```

#### UC-IF3: Verification challenge handshake (WhatsApp / Meta)

```gherkin
Given the inbound entry has verify_token = "abc123"
And an external provider issues GET /hooks/whatsapp?hub.mode=subscribe&hub.verify_token=abc123&hub.challenge=xyz
When handle_get runs
Then it checks mode == "subscribe", token matches verify_token, challenge is present
And returns Response(content="xyz", media_type="text/plain") with 200
And NO HookEvent is created, NO dispatch happens
```

#### UC-IF4: Verification challenge rejected

```gherkin
Given a GET request arrives without the correct verify_token, or with a missing mode
When handle_get evaluates the params
Then it raises HTTPException(status_code=403, detail="Verification failed")
```

#### UC-IF5: GET on non-verification endpoint returns 405

```gherkin
Given the inbound entry has no verify_token set
When any GET request arrives at the registered path
Then handle_get raises HTTPException(status_code=405, detail="GET not supported for this endpoint")
```

#### UC-IF6: HMAC signature verification

```gherkin
Given the inbound entry has secret = "shared-key" and the path is /hooks/github
And a POST request arrives with header X-Hub-Signature-256 = "sha256=<expected>"
When handle_post processes the request
Then it reads the raw body bytes
And computes hmac.new(secret, body, sha256).hexdigest()
And compares against the signature header using hmac.compare_digest
And on match: proceeds to normalization
And on mismatch: raises HTTPException(401, "Invalid signature")
And on missing header (with secret configured): raises HTTPException(401, "Missing signature")
```

#### UC-IF7: Non-string secret rejected with 500

```gherkin
Given verify_config["secret"] is non-string (misconfiguration, e.g., a dict)
When handle_post evaluates the secret
Then a warning "Ignoring non-string secret config for inbound webhook" is logged
And HTTPException(500, "Invalid webhook secret config") is raised
```

#### UC-IF8: Invalid JSON body returns 400

```gherkin
Given a POST request arrives with body that does not parse as JSON
When handle_post calls json.loads
Then HTTPException(400, "Invalid JSON payload") is raised
And the exception is logged
```

#### UC-IF9: Missing normalizer returns 500

```gherkin
Given the normalizer_key is not registered in NormalizerRegistry
When handle_post looks up the normalizer
Then HTTPException(500, "Normalizer not configured") is raised
And the error is logged
```

#### UC-IF10: Normalizer raising → 400

```gherkin
Given the normalizer raises an exception while parsing
When handle_post invokes _invoke_normalizer
Then the exception is caught
And HTTPException(400, "Failed to normalize payload") is raised with the original exception chained
```

#### UC-IF11: Dispatch escape vs swallowed handler failures

```gherkin
Given normalization succeeded and produced one or more HookEvents
And HookDispatcher.dispatch internally catches per-Contract handler exceptions and webhook-enqueue exceptions, logging them and continuing to the next match
When dispatch returns normally (the common case, even when individual handlers raised inside)
Then handle_post returns {"status": "accepted"} with HTTP 200
And the provider sees a successful delivery (no retry)

Given an exception ESCAPES HookDispatcher.dispatch itself (e.g., the matcher faults, the contract iteration crashes, or a downstream component raises outside the per-Contract try/except)
When self._dispatch(event) raises
Then handle_post's outer try catches the exception
And HTTPException(502, "dispatch error") is raised
And the provider (WhatsApp, GitHub) interprets 502 as transient and retries delivery

In v1 practice, handler exceptions do NOT trigger 502 — they are
absorbed by dispatch. Operators inspecting "missing" inbound events
must check daemon error logs for the per-Contract "Internal handler
failed" entries.
```

#### UC-IF12: Multi-event normalizer

```gherkin
Given a normalizer returns a list[HookEvent] (e.g., WhatsApp may carry multiple messages in one webhook)
When handle_post processes the normalized result
Then it iterates and dispatches every event in order
And returns {"status": "accepted"} on completion
```

#### UC-IF13: Duplicate path registration is ignored

```gherkin
Given InboundEndpointRegistry.register(path, ...) was already called for that path
When a second call arrives for the same path
Then a warning "Inbound path already registered" is logged
And the function returns without re-mounting routes
```

#### UC-IF14: Normalizer signature compatibility

```gherkin
Given a normalizer's signature accepts only (payload) — the legacy form
When _invoke_normalizer inspects the signature
Then it detects the lack of headers support
And invokes the normalizer with payload only
Given a normalizer accepts (payload, headers) or *args
When the same invocation runs
Then the normalizer is called with both arguments
```

### Implementation pointers (v1)

- `teleclaude/hooks/inbound.py` —
  `NormalizerRegistry` (L27),
  `InboundEndpointRegistry` (L43, with `register` and inline
  `handle_get` / `handle_post` closures inside it),
  `_invoke_normalizer` (static, L155).
- `teleclaude/hooks/config.py` —
  `load_hooks_config` (L85),
  `_resolve_inbound_registration` (L71),
  `_build_config_contract` (L51),
  `parse_criterion` (L18).
- `teleclaude/hooks/normalizers/__init__.py` —
  `register_builtin_normalizers` (L10, registers `github` and `whatsapp`).
- `teleclaude/daemon_event_platform.py` —
  `_init_webhook_service` (L464, hosts the inbound wiring):
  `NormalizerRegistry()` (~L522), `register_builtin_normalizers` (~L523),
  `InboundEndpointRegistry(app, normalizer_registry, dispatcher.dispatch)`
  (~L531), `await load_hooks_config(...)` (~L534).
- Config schema: `teleclaude/config/schema.py` `HooksConfig` (L285):
  `inbound: dict[str, InboundSourceConfig] = {}`,
  `subscriptions: list[SubscriptionConfig] = []`.

### Cross-context references

- This is the canonical inbound boundary for the `integration` context.
- Dispatch callback wires through `eventbus-hook-bridge`'s
  `HookDispatcher.dispatch` to the Contract registry's matcher.
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
  configuration-driven activation, not from baseline daemon startup.
- HMAC signature verification accepts EITHER `X-Hub-Signature-256`
  (GitHub-style) OR `X-Hook-Signature` (TeleClaude internal contract
  delivery format). The same handler serves both naming conventions.
- The verification challenge handler is hard-coded to the Meta /
  WhatsApp `hub.mode=subscribe` protocol; other providers requiring
  challenge handshakes would need code changes, not config.
- The framework does NOT enforce an allowlist on event NAMES — only
  on path mounting. Any event the normalizer produces is forwarded to
  the dispatcher; allowlist enforcement is a Contract-level concern in
  v1.
- HTTP 502 on dispatch failure invites provider retries; the dispatcher
  itself does NOT implement provider-side dedupe — duplicate deliveries
  from retried providers will produce duplicate HookEvents.
- The framework mounts routes on whichever FastAPI `app` the daemon
  passes; if the API server is not available at startup, inbound
  registration is skipped with a warning and inbound endpoints remain
  inactive until restart.
