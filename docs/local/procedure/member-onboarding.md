---
description: Register a person and issue an invitation whose platform links bind their account to their personal assistant.
visibility: public
---

# Member Onboarding — Procedure

## Required reads

@docs/local/design/architecture/help-desk-platform.md
@docs/local/spec/messaging.md

## Goal

Give a registered person usable links to their personal assistant, with the
invitation and delivery outcome recorded truthfully.

## Preconditions

- The person to invite and the intended invitation delivery are established.

<!-- planned-change:master-conversation-entry -->

- The person is registered with an email address on the computer issuing the
  invitation, and the intended public providers are configured there.

<!-- change:master-conversation-entry -->

- The person is registered with an email address on the unique master, and its
  intended public conversation providers are configured there. Person setup on
  that computer uses the computer-addressed configuration surface.

<!-- /planned-change:master-conversation-entry -->

- Configuration authority follows
  `local/projects/teleclaude/spec/feature/config/kind-addressed-configuration`.

## Steps

### 1. Establish the person

Use `telec config person init <name> --email <email>` when the person is not
registered, then use the returned slug for subsequent operations. Initialization
creates the person declaration and home; invitation is a separate act. Company
memberships and project assignments follow their configuration owners.

### 2. Issue the invitation

<!-- planned-change:master-conversation-entry -->

Run `telec config person invite <person>` on the computer whose public bot
endpoints should appear in the invitation. The command validates the person,
issues a token through the invitation store and resolves the configured provider
links. A resend uses the same command and rotates the person's invitation.

<!-- change:master-conversation-entry -->

Run `telec config person invite <person>` from any computer. The command resolves
its master owner automatically; the complete invitation operation and its
result follow `local/projects/teleclaude/spec/feature/config/person-invitations`.
Use the returned canonical links. A resend uses the same command and rotates the
invitation through that owner.

<!-- /planned-change:master-conversation-entry -->

The command attempts email delivery when available and returns generated links
when email is unavailable or fails. Use `--json` for the structured links and
email outcome. Preserve the returned outcome rather than inferring email
success from token issuance.

### 3. Record expertise

Before or shortly after issuing the invitation, assess the member's expertise
and record it in their person profile using the declared expertise taxonomy.
Read `telec config person get <person>` and carry its revision into the person
patch. Apply `general/spec/expertise-taxonomy` rather than inferring expertise
from invitation or account-binding events.

### 4. Confirm entry

The person opens the selected provider link and uses its entry gesture. Discord
entry uses the invitation token as a direct message. The conversation-entry
contract owns token resolution, existing-account conflicts, endpoint selection
and session continuation
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).

## Outputs

- A registered person and an issued or rotated invitation.
- Generated provider links and an explicit email-delivery outcome.
- On successful redemption, an account binding and conversation entry governed
  by the owning identity and runtime contracts.

## Recovery

- A missing person or missing email is corrected through the person configuration
  surface before retrying invitation.
- Failed provider resolution leaves that provider link unavailable; inspect the
  reported result and correct its provider configuration through the supported
  surface before retrying.
- Email failure leaves any generated links available for the intended delivery.
  Retrying invitation rotates the token, so use the returned replacement links.
- A binding conflict follows the entry contract's refusal; it does not overwrite
  a different person's provider account.

## See Also

- docs/local/spec/feature/agent_runtime/conversation-entry.md
- docs/local/spec/feature/config/kind-addressed-configuration.md
- docs/global/general/spec/expertise-taxonomy.md
