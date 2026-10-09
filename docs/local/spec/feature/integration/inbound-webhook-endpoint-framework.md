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
  the project's secret. It is relayed as `github.<event>`, where `<event>` is
  GitHub's event type for the delivery, with the delivery body as its data.
- A WhatsApp webhook is verified with Meta's signature over the raw body under
  the global WhatsApp secret. Each message it carries is relayed as one event,
  `whatsapp.message.<type>`, with that message as its data. A webhook that
  carries no message is accepted and relays nothing.

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

### Use cases

#### UC-IF3: Verification challenge handshake (WhatsApp / Meta)

```gherkin
Given the global configuration declares the WhatsApp source with verify token "abc123"
And Meta issues a verification challenge with mode=subscribe, verify_token=abc123, challenge=xyz
When the ingress handles the challenge
Then it echoes the challenge value as plain text in the accepted response
And no event is relayed
```

#### UC-IF4: Verification challenge rejected

```gherkin
Given a verification challenge arrives without the declared verify token, or with a missing mode
When the ingress evaluates the parameters
Then it rejects the challenge as forbidden
```

#### UC-IF5: Verification on a native or GitHub endpoint is unsupported

```gherkin
Given a native or GitHub endpoint
When a verification challenge arrives at it
Then the ingress rejects it as method-not-supported
```

#### UC-IF8: Invalid body returns a client error

```gherkin
Given a correctly signed request whose body does not parse as a structured payload
When the ingress handles it
Then the request is rejected with an "invalid payload" client error
And nothing is relayed
```

#### UC-IF12: Multi-message WhatsApp webhook

```gherkin
Given a verified WhatsApp webhook carries several messages
When the ingress handles it
Then it relays one event per message, in order
And returns an accepted response
```

#### UC-IF16: A home's own declaration opens its native endpoint

```gherkin
Given the company "acme" declares a native source in its own configuration, with its secret in its own .env
When a producer posts a request signed with that secret to /hooks/inbound/company/acme
Then the ingress accepts it
And relays an event whose origin is the company "acme"
And whose subject is that company's native source
```

#### UC-IF17: A path no declaration opens has no endpoint

```gherkin
Scenario Outline: Only a home's own declaration opens an endpoint in its name
  Given <situation>
  When a signed request arrives at <path>
  Then the ingress responds not found
  And nothing is relayed

  Examples:
    | situation                                              | path                                   |
    | the company "acme" declares no native source           | /hooks/inbound/company/acme            |
    | no home "ghost" is registered on the ingress           | /hooks/inbound/person/ghost            |
    | the project "web" declares a native but no GitHub source | /hooks/inbound/github/project/web    |
```

#### UC-IF18: Every request is signed

```gherkin
Scenario Outline: An unsigned or wrongly signed request is refused
  Given the project "web" declares a GitHub source
  When a delivery arrives at /hooks/inbound/github/project/web <signature>
  Then the ingress responds unauthorized
  And nothing is relayed

  Examples:
    | signature                                  |
    | with no signature                          |
    | signed with a different secret             |
    | signed with the project's secret but carrying the native protocol's signature instead of GitHub's |
```

#### UC-IF19: A source without a secret cannot be declared

```gherkin
Given a home's configuration declares a native source with no secret
When that configuration is validated
Then validation fails and names the missing secret
And the ingress opens no endpoint for that home
```

#### UC-IF20: A declaration takes effect without a restart

```gherkin
Given the ingress is running
And the person "mo" declares no native source
When a native source is added to that person's configuration, with its secret in their .env
And a request signed with that secret arrives at /hooks/inbound/person/mo
Then the ingress accepts it and relays the event
```

#### UC-IF21: TeleClaude relays the native payload without interpreting it

```gherkin
Given a project declares a native source
When its producer posts a signed request with domain "erp", name "invoice.overdue.reminded" and a payload object with any members
Then the relayed event is named "erp.invoice.overdue.reminded"
And its data is exactly the payload the producer sent
```

#### UC-IF22: A malformed native event name is refused

```gherkin
Scenario Outline: The relayed name is built only from well-formed segments
  Given a project declares a native source
  When its producer posts a signed request with domain <domain> and name <name>
  Then the ingress rejects it with a client error
  And nothing is relayed

  Examples:
    | domain  | name           |
    | ""      | "paid"         |
    | "erp"   | ""             |
    | "Erp"   | "paid"         |
    | "erp"   | "invoice..paid"|
    | "e.rp"  | "paid"         |
```

#### UC-IF23: A failed relay asks the sender to retry

```gherkin
Given a verified request
When relaying it to the cluster fails
Then the ingress responds with a transient failure status
And the sender may deliver the request again
```

#### UC-IF24: An unreadable declaring home is a server error

```gherkin
Given the project "web" declares a GitHub source whose secret references a name missing from its .env on the ingress
When a delivery arrives at /hooks/inbound/github/project/web
Then the ingress responds with a server error
And the error record names the project and the unresolved reference, never a secret
```

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

- A provider retries a transient failure, and the ingress does not deduplicate
  retried deliveries. A retried request is relayed as a new event; consumers own
  the idempotency of their work.
- The ingress must hold the configuration and `.env` of every home that
  receives external events, because verification happens there.
- The subscription handshake is Meta's protocol; the native and GitHub
  endpoints answer no handshake.

## See Also

- docs/local/adr/0055-proxy-fronted-ingress-reuse.md
- docs/local/adr/0111-external-events-enter-as-ordinary-platform-events.md
