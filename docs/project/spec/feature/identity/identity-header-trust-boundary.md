---
description: "Reject web-user identity signals at the identity context's transport boundary unless the call originates from a trusted loopback host."
visibility: 'public'
---

# Identity Header Trust Boundary — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The transport-level firewall that protects the identity context from forged web identities. The local web frontend authenticates a browser session, then forwards the resolved user to the identity context as a trio of signals — web-user email, web-user name, web-user role. Those signals are the v1 substitute for a signed web token: downstream resolution (caller verification, session-access visibility, the session-visibility filter, the inbound session-list listener) trusts them without any further cryptographic check. That trust only holds if the signals cannot be supplied by an outside caller. A boundary check enforces the constraint at the edge: if any of the three identity signals appears on a call whose client host is not a loopback address, the call is refused with an untrusted-source authorization failure before any downstream logic runs. The boundary check is what makes the rest of the v1 identity model safe; without it, the signals would be a self-service role escalation.

## Canonical fields

### Use cases

```
Given a call from a non-trusted client host (e.g. 192.0.2.10)
And the call carries the web-user email signal `maurice@instrukt.ai`
When the identity-headers boundary check evaluates the call
Then the call is refused as "Identity headers rejected: untrusted source"
And a warning is logged naming the rejected client host
And no downstream resolution runs
```

```
Given a call from 127.0.0.1
And the call carries web-user email `maurice@instrukt.ai` and web-user role `member`
When the boundary check evaluates the call
Then the call passes through unchanged
And caller verification consumes the signals via the terminal-identity path
And the caller is treated as the named web user
```

```
Given a call over the identity context's local-socket transport (no client host is populated)
And the call carries the web-user email signal
When the boundary check evaluates the call
Then the empty / None client host is treated as trusted
And the call proceeds
```

```
Given a CLI tool call (no web-user-* signals present) from any client host
When the boundary check evaluates the call
Then the trust boundary does not engage
And the call proceeds to be authenticated by caller verification via session-token or terminal-email paths
```

```
Given a streaming-session upgrade from 127.0.0.1 carrying web-user email / role
When the identity context receives the upgrade
Then the boundary check applies on the upgrade exchange
And the streaming session-list listener reads the same signals to apply role-based visibility filtering
```

```
Given a call from a non-trusted host carrying only the web-user name signal (with no email and no role)
When the boundary check evaluates the call
Then the call is still refused
Because ANY of the three identity signals triggers the trust check
```

### Cross-context references

- The signals themselves are produced by the local-only web frontend's auth flow described in `identity-and-auth.md` §4 (web identity). The frontend is owned by the `integration` bounded context; the boundary check is owned by the identity context and lives on the inbound transport surface.
- Once admitted, the signals feed the terminal-identity path of `feature/identity/caller-verification` (web user) and gate `feature/identity/session-access-visibility` (which sessions that user may touch) and the session-list role filter consumed by the streaming session feed.
- The web-user email signal is an alternative to the CLI's terminal-email signal — both produce the same `human_email` on the resolved `CallerIdentity`. The trust boundary is what makes them safe to treat equivalently: only the terminal-email signal is set by trusted local CLI processes, and the web-user email signal is gated by this boundary check.

## Known caveats

- The trust boundary is HOST-based, not user-based. Any process running on the identity context's host that can reach the loopback transport can forge any web user identity. The v1 deployment assumption is that the host is single-tenant operator hardware; this assumption is documented in `identity-and-auth.md` and tightened by v2.
- A client host of `None` or empty string is treated as trusted to support local-socket transport, where the inbound transport does not populate a client host. This is correct for the intended local-socket case but means any future transport that leaves the client host unset will also be treated as trusted — a coupling worth re-checking before adding new transports.
- The boundary fires on the presence of ANY of the three signals, not just web-user email. A call that supplies only the web-user name signal from an untrusted host is still refused. This is intentional fail-closed behavior — the trio is treated as a single identity assertion.
- v2 hardens this by introducing a config-driven trust gate (per the v2 identity domain spec's Known caveats) so the trusted-host set is not hard-coded.
- The boundary check does not run on streaming frames after the upgrade, only on the upgrade exchange itself. Streaming consumers that read the web-user email signal from the upgrade rely on the upgrade-time check; a streaming upgrade from an untrusted host carrying identity signals is rejected at the upgrade, so post-upgrade reads are only ever of signals that passed the boundary.
