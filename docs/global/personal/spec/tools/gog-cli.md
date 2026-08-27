---
description: The permitted gog invocations for personal Gmail and Calendar work, the per-person state root, and the gates the tool enforces.
---

# gog CLI — Spec

## What it is

`gog` is the command-line tool through which all Google access happens — reading
mail and calendar, and preparing drafts. It is never reached through an MCP
server: one pathway means one place the gates live.

Every person has their own state root under their workspace, holding their
accounts, tokens, aliases and per-account settings. Which person's mail a
command touches is decided entirely by that root, and it is selected for the
agent — an agent does not choose an account, and does not see the unwrapped
binary.

## Canonical fields

### Reading

- Search a mailbox with Gmail's own query syntax; fetch a message or a thread by
  id; list calendar events for a window. These carry no side effects and need no
  mandate beyond the work being done.

### Writing — the permitted set

- **Draft creation.** Replies pass the flag that sends from the alias the
  original was addressed to, together with the thread and quoting flags, so a
  reply lands in its thread from the right identity. Fresh outbound names the
  address explicitly, chosen from the person's identity registry.
- **Mailbox operations** — labelling and label management, filing, archiving,
  marking read or unread, trashing and restoring.
- **Calendar operations** — creating, updating, moving, cancelling events, and
  answering invitations.
- **Attachments** — saving what arrives into the person's workspace.
- **Sending** — available only to carry out a send the person asked for. What
  the agent composed of its own accord is left as a draft instead.

Writing as one of the person's identities is part of composing a message and
needs no authority over their settings: a draft or a message carries whichever
of their verified addresses it is sent from, and the list of those addresses is
readable. Changing which identities exist — adding one, verifying it, altering
its signature or default, granting delegation — is a settings operation and is
refused. A request to send as an identity is therefore never a reason to widen
the grant.

All of these are ordinary writes governed by the mandate rule, not by this
spec: the tool permits them, and the conduct policy decides when they run.

### Refused by the tool

<!-- planned-change:personal-mail-tool-launcher -->
Every settings operation, on every path — send-as identities, forwarding,
filters, vacation responders, anything that silently reroutes future mail. These
appear in no allowlist, and the policy compiled into the binary holds the rule
where no flag, environment variable, or configuration can lift it.

Sending is refused on the same terms in an unattended run, which uses a build
that has no send at all. Where the stronger wall is wanted for an attended run
too, a persistent per-account guard holds it.
<!-- change:personal-mail-tool-launcher -->
Every settings operation, on every path — send-as identities, forwarding,
filters, vacation responders, anything that silently reroutes future mail. The
tool carries these commands, so the refusal is held in two places outside them.
The account's authorization grant excludes the Gmail settings scopes, so the API
refuses them whatever is invoked. And the boundary that launches the tool
constructs every invocation with the tool's own command restrictions already
applied, so the commands are unreachable before they are attempted.

Sending is held the same way rather than by the tool's own disposition: the tool
can send, and the launch boundary is what withholds it, constructing an
unattended invocation with sending blocked.
<!-- /planned-change:personal-mail-tool-launcher -->

An agent that receives a refusal reports it; it does not look for another route.

## Known caveats

<!-- planned-change:personal-mail-tool-launcher -->
- The person's tokens live in their own state root. On a machine with a single
  operating-system account, separation between persons is organizational rather
  than enforced by the system — real isolation means separate machines or
  accounts.
<!-- change:personal-mail-tool-launcher -->
- The person's tokens live in their own state root, and their stored secrets are
  confined to it because every invocation is constructed with the tool's
  file-backed secret store and that person's own store password. A state root on
  its own does not separate people: it relocates configuration while account
  resolution still reaches the machine-wide secret store, which looks like
  isolation and is not.
<!-- /planned-change:personal-mail-tool-launcher -->
- Google's authorization is a one-time human ceremony per account. Until it is
  done, every command fails for that account and the assistant says so instead
  of working around it.
- The exact flag spellings live in the tool's own help. This spec fixes what is
  permitted, not how the tool spells it.
