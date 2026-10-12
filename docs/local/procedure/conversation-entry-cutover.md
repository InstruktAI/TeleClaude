---
description: Verify master-owned conversation entry before disabling secondary Telegram receivers and retiring their obsolete bot identities without discarding history or stranding active senders.
delivered_by:
  - master-conversation-entry
---

# Conversation Entry Cutover — Procedure

## Goal

Activate one verified public conversation owner and retire the secondary
Telegram bots while preserving historical records and supported delivery.

## Preconditions

- The operator holds the concrete mandate to disable the secondary Telegram
  adapters and retire their obsolete bot identities.
- The master-entry implementation and its dependencies are deployed on the
  participating computers and their supported remote command surface is working.
- Runtime discovery and provider account-management access are available.
- The governing behavior is
  `local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry` and
  `local/projects/teleclaude/spec/feature/config/person-invitations`.

## Steps

1. Discover the computers and projects with `telec computers list` and
   `telec projects list --computer <computer>`. Inspect their resolved master
   ownership and adapter configuration through the configuration surface. Record
   the single master and the actual provider identities involved in the private
   task record, using public bot identity rather than secret token values.
2. Verify the canonical public endpoints and invitation flow with a controlled
   test account. An invitation requested from a peer must be issued on the
   master and redeem there. Verify a normal conversation and its continuation,
   and the compaction, closure, mirror-readiness and extraction chain. Preserve
   the observation addresses and any provider-execution gaps in the task record.
3. Exercise non-master conversational rejection and verify that the relevant
   peers produce no session, identity mutation, media work or conversational
   reply. Confirm that their Discord project forums and controls still work.
   These observations are separate from checking the configured master flag.
4. Account for secondary bot consumers before retiring identities: invitations,
   retained conversation bindings, person-addressed notifications, direct send
   helpers, scheduled jobs and external callers known to the operator. Preserve
   histories and source provenance. Record each active dependency and the
   supported route that replaces it; an unresolved dependency keeps that bot
   identity retained until its migration is complete
   (`general/principle/trust-and-guardrails`).
5. Disable the secondary Telegram adapters through computer-addressed
   `telec config computer patch`, using the revision from that computer's current
   configuration read. Apply any required service activation through the owning
   computer's supported `make` targets. Confirm that secondary receivers are
   inactive while the master still receives and answers the controlled account.
6. Once the recorded dependencies are resolved and the master flow is verified,
   remove only the obsolete secondary bot identities through the provider's
   supported account-management surface. Confirm their identities against the
   recorded inventory before each removal. Preserve the canonical master bot,
   Discord application, WhatsApp account and TeleClaude historical records.
7. Remove obsolete credential references through their owning configuration
   operations after provider retirement. Verify the master invitation and
   conversation flow again and record the exact completed retirements and any
   remaining work. Provider-account removal and local adapter disabling are
   separate outcomes; report each from its evidence.

## Outputs

- Verified master-owned invitations and conversational entry.
- Secondary Telegram adapters disabled on the identified computers.
- Obsolete secondary Telegram bot identities retired only after dependency
  migration, with historical TeleClaude records retained.
- A task record containing verification addresses, actual configuration and
  provider outcomes, and any unresolved dependency.

## Recovery

- An ownership conflict or failed canonical flow stops retirement. Preserve the
  existing bot identities and repair the named problem before continuing.
- A failed configuration mutation is recovered through the configuration
  context; a failed service activation uses the owning `make` targets.
- An active sender still depending on a secondary bot is concrete migration
  work. Resolve it through its owning delivery contract before deleting the
  identity; do not replace it with an unsupported send route.
- Missing provider account-management access leaves retirement pending with the
  exact required access stated. Successful adapter disabling is not evidence
  that the provider bot was removed.

## See Also

- ~/.teleclaude/docs/general/procedure/machine-config-editing.md
- docs/local/policy/agent-service-control.md
- docs/local/spec/messaging.md
