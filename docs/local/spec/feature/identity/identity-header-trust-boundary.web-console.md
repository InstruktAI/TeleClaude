---
description: "Honour carried identity only on the daemon's Unix socket; drop it on any other listener. The web service is the browser's authenticated edge and the only thing that turns a browser session into carried identity."
visibility: 'public'
---

# Identity Header Trust Boundary — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The transport rule that keeps carried identity honest. A client resolves its
caller in its own process and carries the result to the daemon as identity
headers — `x-caller-principal`, `x-caller-email`, `x-caller-entry-point` and the
session fields — and the daemon takes them as given without lookup or
verification. That trust holds because of where the headers can arrive: the
daemon's Unix socket, reachable only by processes running as the daemon's own
operating-system user. The boundary check enforces exactly that. The loopback
TCP listener the ingress computer opens serves the inbound webhook endpoints
and nothing else: any other path requested on it is refused as not found,
whatever headers the request carries. On the inbound endpoints caller headers
carry nothing: they are dropped before the endpoint runs, and the request
reaches the endpoint carrying no identity. What the endpoint then does with the
request is the inbound endpoint framework's contract.

The web service is the one client that turns a browser into a caller. It
authenticates the person itself — invitation link, passkey, recovery code,
host-only cookie, `Origin` check — then connects to the socket and carries that
person's identity with entry point `web`. Headers a browser sends are never
forwarded: the web service drops any caller header on an inbound browser
request and sets its own. The daemon never sees a browser.

## Canonical fields

### Use cases

```
Given a request on the daemon's Unix socket
And the request carries x-caller-principal human:operator@example.com and x-caller-entry-point web
When the trust boundary evaluates the request
Then the request passes through unchanged
And caller resolution treats the caller as that person
And the person band is decided from the principal at the scope of the object addressed
```

```
Given a request on the loopback TCP listener for any path outside the inbound webhook endpoints
And the request carries any caller header (principal, email, entry point, or session)
When the trust boundary evaluates the request
Then the request is refused as not found
And no route runs
And the carried identity is never read
```

```
Given an inbound webhook request on the loopback TCP listener
And the request carries caller headers naming a session
When the trust boundary evaluates the request
Then every caller header is dropped
And the request reaches the inbound endpoint carrying no identity
```

```
Given a WebSocket upgrade on the loopback TCP listener
When the daemon receives the upgrade
Then the upgrade is refused as not found
Because the stream endpoint is served on the Unix socket only
```

```
Given a browser request to the web service carrying x-caller-principal
When the web service accepts the request
Then the supplied header is discarded
And the request runs as the person the web service authenticated, or is refused when nobody is authenticated
And the request the web service makes to the daemon carries the authenticated person's identity only
```

```
Given a person authenticated by the web service
When the web service acts on the daemon for that person
Then every request and WebSocket upgrade travels over the Unix socket
And never over the loopback TCP listener
```

### Cross-context references

- The headers and their meaning are owned by
  `local/projects/teleclaude/spec/identity-and-auth`; this boundary decides on
  which transport they are honoured, and lives on the daemon's inbound
  transport surface in the identity context.
- The web service is owned by the `integration` bounded context
  (`local/projects/teleclaude/design/architecture/web-console`); its
  authentication of a person is the boundary a human crosses, in the same sense
  as the terminal login for `telec` and the TUI.
- Once admitted, carried identity feeds
  `local/projects/teleclaude/spec/feature/identity/caller-verification` and the
  scoped-role decision, and gates
  `local/projects/teleclaude/spec/feature/identity/session-access-visibility`.
- The loopback TCP listener and its inbound endpoints are owned by
  `local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`,
  which owns the outcome of a request that reaches an inbound endpoint.

## Known caveats

- The boundary is transport-based, not user-based. Any process running as the
  daemon's operating-system user can carry any identity over the socket; that is
  the premise clients authorize and the daemon trusts, and the host is assumed to
  be single-tenant operator hardware.
- A transport added later is untrusted by default: it honours carried identity
  only once this boundary names it, and a listener that leaves the transport
  unidentified is treated as untrusted.
- On the inbound endpoints the boundary drops every caller header, not only the
  principal; the headers are one identity assertion, and a request is never
  refused on their account.
- The TCP listener's confinement to the inbound endpoints holds whether or not
  the reverse proxy in front of it forwards only the inbound path prefix.
- The socket-side check runs on the upgrade exchange, not on WebSocket frames
  afterwards; a stream only exists where the upgrade passed.
