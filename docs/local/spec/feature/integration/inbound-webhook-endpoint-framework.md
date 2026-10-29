---
description: 'The ingress inbound endpoints: a home declares its source in its own teleclaude.yml with a secret from its own .env, the endpoint path is derived from the declaring home, every request is signed, and the native protocol carries a domain, a name and an opaque payload that TeleClaude relays without interpreting.'
visibility: 'public'
---

# Inbound Webhook Endpoint Framework — Spec

## What it is

The inbound endpoints the ingress computer serves, and the declarations that
open them. A home opens an endpoint in its own name by declaring a source in
its own `teleclaude.yml`, with the source's secret resolved from that home's
own `.env` (`local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`).
The path is derived from the declaring home and the source's protocol; it is
never configured. The declaration shape is owned by the configuration models
(`local/projects/teleclaude/spec/teleclaude-config`).

Three protocols exist:

- **Native.** A producer that is ours, such as an app another repository
  ships, sends a signed request carrying a domain, a name and an opaque
  payload. TeleClaude verifies the request and relays it. It never parses or
  validates the payload and holds no knowledge of the producer's domain.
- **GitHub.** A project receives GitHub webhooks, verified with GitHub's own
  signature.
- **WhatsApp.** The platform receives WhatsApp Cloud API webhooks for its own
  number, verified with Meta's signature and answering Meta's subscription
  handshake.

A verified request is relayed as an ordinary platform event under
`local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`.
Only the ingress computer serves these endpoints.

## Canonical fields

### Endpoints

| Path                                   | Opened by                                                        | Protocol | Relayed origin                  |
| -------------------------------------- | ---------------------------------------------------------------- | -------- | ------------------------------- |
| `/hooks/inbound/<kind>/<slug>`         | a native source declared by that company, person or project home | native   | that company, person or project |
| `/hooks/inbound/github/project/<slug>` | a GitHub source declared by that project                         | GitHub   | that project                    |
| `/hooks/inbound/whatsapp`              | the WhatsApp source declared by the global configuration         | WhatsApp | none                            |

Every relayed event's subject is the declared source that received it.

`<kind>` is one of the registered home kinds, company, person or project, and `<slug>` is that home's
slug as registered on the ingress computer. A home declares at most one source
per protocol, and only the protocols its tier admits: a native source in a
company, person or project home; a GitHub source in a project; the WhatsApp
source in the global configuration.

### Declaration and resolution

- Every source declares its secret as a `${NAME}` reference into the declaring
  home's `.env`. A declaration without one does not validate. The WhatsApp source
  additionally declares the token Meta's subscription handshake presents. Only
  the ingress needs the values: they may be absent on any other computer, and
  validation on the ingress refuses a declaration whose values have no value
  in the declaring home's `.env`.
- The ingress reads the declaring home's configuration when a request arrives,
  so a declaration added, changed or removed takes effect on the next request
  without a restart.
- A path whose home is not registered on the ingress, or whose home declares
  no source of that protocol, has no endpoint.

### Native request

- The body is a JSON object with exactly three members: `domain`, a single
  name segment; `name`, one or more name segments joined by dots; and
  `payload`, a JSON object.
- A name segment starts with a lowercase letter and holds only lowercase
  letters, digits and underscores.
- The request is signed with the platform's webhook signature: an
  HMAC-SHA256 digest of the raw body under the declaring home's secret,
  presented as `sha256=<hex digest>` in the `X-Hook-Signature` header.

- The relayed event is named `<domain>.<name>` and carries `payload` as its
  data.

### Provider requests

- A GitHub delivery is verified with GitHub's signature over the raw body under
  the project's secret. It arrives in either content type GitHub offers: a JSON
  body, or a form-encoded body whose single `payload` field holds the same JSON
  document. It is relayed as `github.<event>`, where `<event>` is GitHub's event
  type for the delivery, with that JSON document as its data, so both content
  types relay the same event.

- A WhatsApp webhook is verified with Meta's signature over the raw body under
  the global WhatsApp secret. Each message it carries is relayed as one event,
  `whatsapp.message.<type>`, with that message as its data. A webhook that
  carries no message is accepted and relays nothing.
  When one webhook carries several messages, each is relayed as one event in
  the order received. Meta's subscription handshake accepts only `subscribe`
  mode with the configured verify token, echoes the challenge as plain text,
  and relays no event; a missing mode or token is forbidden.

### Responses

| Request                                           | Response                                 |
| ------------------------------------------------- | ---------------------------------------- |
| No endpoint exists for the path                   | not found; nothing relayed               |
| Signature missing or invalid                      | unauthorized; nothing relayed            |
| Body malformed for its protocol                   | client error; nothing relayed            |
| The declaring home's configuration cannot be read | server error; nothing relayed            |
| Relaying fails                                    | transient failure, so the sender retries |
| Verified and relayed                              | accepted                                 |

The signature is checked before the body is read as a structured payload, and
with a constant-time comparison. No response and no log record carries a secret.
If secret resolution prevents reading a declaring home's configuration, the
error record identifies that home and unresolved reference without recording a
secret.

### Use cases

#### UC-IF3: Verification challenge handshake (WhatsApp / Meta)

#### UC-IF4: Verification challenge rejected

#### UC-IF5: Verification on a native or GitHub endpoint is unsupported

#### UC-IF8: Invalid body returns a client error

#### UC-IF12: Multi-message WhatsApp webhook

#### UC-IF16: An operator can expose a company's native event source

```gherkin
Given an operator has configured a native source for the company "acme"
When the company's producer sends a valid signed request to that source
Then the ingress accepts it and relays an event whose origin is the company "acme"
And whose subject is that company's native source
```

#### UC-IF17: A path no declaration opens has no endpoint

#### UC-IF18: Every request is signed

#### UC-IF19: A source without a secret cannot be declared

#### UC-IF20: A person can add a native source while ingress is running

```gherkin
Given a person has a running ingress and no native source in their configuration
When they add a native source and its secret to their own configuration
And a valid signed request arrives before ingress restarts
Then the ingress accepts the request without a restart and relays the event
```

#### UC-IF21: TeleClaude relays the native payload without interpreting it

#### UC-IF22: A malformed native event name is refused

#### UC-IF23: A failed relay asks the sender to retry

#### UC-IF24: An unreadable declaring home is a server error

#### UC-IF25: A GitHub delivery is accepted in either content type GitHub offers

#### UC-IF26: A form-encoded GitHub delivery without a single payload document is refused

### Cross-context references

- This is the canonical inbound boundary for the `integration` context.
- Declarations are configuration owned by the `config` context; their
  environment references resolve under
  `local/projects/teleclaude/spec/feature/config/yaml-env-var-expansion`.
- Relay and delivery are owned by
  `local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`.
- The GitHub and WhatsApp translations are owned by
  `local/projects/teleclaude/spec/feature/integration/github-webhook-normalization`
  and
  `local/projects/teleclaude/spec/feature/integration/whatsapp-inbound-conversation-routing`.

## Known caveats

- A provider retries a transient failure. The ingress relays a retried delivery
  once per source while its claim is retained
  (`local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`);
  a retry after the claim expires, or a request whose body differs from the
  original where no delivery identifier exists, is relayed as a new event.
  Consumers own the idempotency of their work.
- The ingress must hold the configuration and `.env` of every home that
  receives external events, because verification happens there.
- The subscription handshake is Meta's protocol; the native and GitHub
  endpoints answer no handshake.

## See Also

- docs/local/adr/0055-proxy-fronted-ingress-reuse.md
- docs/local/adr/0111-external-events-enter-as-ordinary-platform-events.md
