---
activation_trigger: 'Use when a locally built macOS app must reach a network destination without a per-connection firewall prompt on every rebuild, or when delivering application work that opens a new outbound destination on macOS'
description: 'Grant locally built macOS apps their network destinations through a declarative, version-controlled rules artifact the per-connection firewall subscribes to, so rebuilds never re-prompt. macOS-only; a no-op where no such filter runs.'
visibility: 'public'
---

# macOS Network Access Rules — Procedure

## Goal

A locally built macOS app reaches the network destinations its work requires without a
per-connection firewall prompting a human on each rebuild. The destinations an app may reach
are declared once in a version-controlled artifact the firewall subscribes to, so delivering
application work that opens a new destination is an edit to that artifact rather than a dialog
someone dismisses.

This is the network half of operating a locally built macOS app autonomously; the identity
half is `software-development/procedure/macos-stable-code-signing`. The app carries one stable
identity across rebuilds, and its destinations are declared once and thereafter applied by the
firewall.

The procedure applies only on macOS, and only where a per-connection outbound firewall is
installed and prompting. Where no such filter runs — a Linux host, or a macOS host without one
— there is nothing to grant and nothing to reflect per delivery; it is a no-op, not a missing
step. Portable delivery documentation names it macOS-only so a non-macOS deployment reads it
and skips it rather than searching for a step that does not apply.

## Preconditions

- The host is macOS and runs a per-connection outbound firewall that prompts. On any other host
  the procedure does not apply.
- The machine's firewall is subscribed once to the rules artifact (see Steps step 1). This is
  the one human-crossed gate, paid once per machine — a firewall a script could subscribe or
  rewrite unattended would not be a firewall.

## Steps

### 1. Keep one rules artifact the firewall subscribes to, and subscribe it once

Maintain a single machine-local rules artifact as the source of truth for the destinations
locally built apps may reach — a declarative file the firewall subscribes to, rather than
rules built by hand in the firewall's own interface. Subscribe the firewall to it once. That
subscription is the machine-setup gate: crossed a single time per machine, alongside creating
the signing identity, and recorded as a precondition rather than repeated per delivery. A
firewall that refuses script-driven subscription is enforcing that gate correctly.

### 2. Declare the destination, not the executable path

Add a rule that allows the destination the work reaches — the host or domain — scoped no wider
than the app requires. Declare it by destination rather than by executable path: a path-bound
rule matches only the exact build location it was written for and prompts again for the next
rebuild or working copy, while a destination the app legitimately reaches is the same across
every build. The firewall's own finer-grained matching is its concern; the artifact's job is
to state where the app is allowed to connect.

### 3. Let the firewall pick up the change; nudge only if it does not

The firewall picks up a change to the subscribed artifact on its own. When a freshly declared
destination is not yet honored, the sanctioned nudge is to restart the firewall's daemon. That
is the only lever the platform reaches for — the artifact is the input, a reload is the nudge,
and how the firewall applies rules between the two is not something the platform models or
reproduces.

### 4. Reflect a new destination as part of delivery

Application work that opens a new outbound destination declares it in the artifact as part of
that delivery, the same way a behavioral change reflects in the doc layer. A destination an
app reaches at runtime but no rule declares is a prompt waiting to fire on the next machine or
the next rebuild; the delivery is complete only when the artifact carries it.

## Outputs

- A machine-local rules artifact, version-controlled, declaring every destination locally
  built apps may reach.
- A firewall subscribed to that artifact once, applying its rules without a per-rebuild prompt.
- Delivery that reflects each new destination in the artifact, evidenced by a rebuild that
  prompted nothing.

## Recovery

- **A prompt returns after a rebuild:** confirm the rule is declared by destination rather than
  by executable path, and that the artifact carries that destination. A path-bound rule matches
  only its original build location and re-prompts for a new one.
- **A newly declared destination is not honored:** the firewall has not yet reloaded the
  artifact. Restart its daemon, then retry.
- **The firewall refuses a script-driven rule change:** that is the machine-setup gate, not a
  fault. The subscription is crossed once by a human; rule content afterwards flows through the
  subscribed artifact, not the firewall's own control surface.

## Discipline

The rules artifact is the source of truth; the firewall is downstream of it. A rule is declared
by destination, never by executable path, so it outlives every rebuild and relocation — a
path-bound rule is a prompt deferred, not prevented. The one human gate is the initial
subscription, paid once per machine and no more; every rule afterwards is an artifact edit an
agent makes and the firewall applies. The platform does not model or reproduce how the firewall
works — it declares destinations and, at most, asks the firewall to reload. On any host without
such a firewall the procedure is inert, and portable delivery documentation names it macOS-only
so a Linux deployment skips it rather than searching for a step that does not apply.

## See Also

- ~/.teleclaude/docs/software-development/procedure/macos-stable-code-signing.md — the identity
  half of operating a locally built macOS app across rebuilds.
