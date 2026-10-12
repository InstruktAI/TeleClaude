---
description: Who receives a person-addressed message — the named person, or by default
  the person whose authority the calling session runs under, with the platform admins
  standing in for system authority.
visibility: internal
---

# Person-Addressed Messaging — Spec

## What it is

Person-addressed delivery sends a message to people rather than to a session.
This spec owns who those recipients are. The command surface, channel routing,
attachments, subject, and the per-send failure contract are owned by
`local/projects/teleclaude/spec/messaging`.

An agent that holds something a human must see sends it without first looking
up who that human is. The default recipient is the person whose authority the
calling session runs under — its lineage chain root, which names the authority
and never the author (`general/concept/lineage-vs-authorship`).

## Canonical fields

### Recipient resolution

- **Named recipient.** A request that names a person delivers to that person
  only, whatever authority the caller runs under.
- **Default recipient.** A request that names nobody delivers to the person the
  caller's principal resolves to: a human principal resolves through the people
  roster by its email to that person's slug.
- **System authority.** A request that names nobody, from a caller whose
  principal is a system principal, delivers to every platform admin on the
  people roster.
- **Unresolvable default.** A request that names nobody is refused, with an
  error stating what did not resolve and that a recipient can be named instead,
  when the caller carries no principal, when its human principal matches no
  addressable person on the roster, or when its system principal finds no
  platform admin. Nothing is delivered.
- **Delivery to several admins.** Each admin is delivered independently on
  their own routed channel. The request succeeds when at least one admin is
  reached, and its result names, per admin, the channel that carried it or the
  reason it was not delivered. The request fails only when no admin is reached,
  and then reports every admin's failure.

### Use cases

#### UC-PAM1: A named recipient receives the message

```gherkin
Given a person registered on the people roster with an addressable slug
When an agent sends a person-addressed message naming that person
Then that person receives it on their routed channel
And nobody else receives it
```

#### UC-PAM2: An unnamed message reaches the person the session runs under

```gherkin
Given an agent session whose authority traces to a person registered on the people roster
When the agent sends a person-addressed message without naming a recipient
Then that person receives it on their routed channel
And nobody else receives it
```

#### UC-PAM3: A system-rooted session's unnamed message reaches every platform admin

```gherkin
Given an agent session running under system authority
And the people roster declares two platform admins
When the agent sends a person-addressed message without naming a recipient
Then each admin receives it on their own routed channel
And the agent is told which admins received it and on which channel
```

#### UC-PAM4: A default recipient that resolves to nobody is refused

```gherkin
Given an agent session whose authority traces to no addressable person on the people roster
When the agent sends a person-addressed message without naming a recipient
Then the send is refused with an error stating the default recipient did not resolve and that a recipient can be named
And nothing is delivered
```

#### UC-PAM5: Admins reached in part are reported, not failed

```gherkin
Given an agent session running under system authority
And one platform admin is reachable and another has no usable credential for their routed channel
When the agent sends a person-addressed message without naming a recipient
Then the reachable admin receives it
And the send succeeds while naming the admin who was not reached and why
```

#### UC-PAM6: Reaching no admin fails the send

```gherkin
Given an agent session running under system authority
And no platform admin is reachable on their routed channel
When the agent sends a person-addressed message without naming a recipient
Then the send fails, naming each admin and why they were not reached
And nothing is delivered
```

<!-- planned:master-owned-providers -->

#### UC-PAM7: A message requested on a non-master computer is delivered by the master

```gherkin
Given a fleet whose master holds the person-facing provider configuration
And an agent session on another computer of that fleet
When the agent sends a person-addressed message naming a registered person
Then that person receives it on their routed channel, sent by the master
And the agent is told the outcome the master reported
```

<!-- /planned:master-owned-providers -->

## See Also

- docs/local/spec/messaging.md — the person-addressed command surface, channel routing, and per-send failure contract.
- ~/.teleclaude/docs/general/concept/lineage-vs-authorship.md — why the default recipient is the authority a session runs under, not who wrote the message.
