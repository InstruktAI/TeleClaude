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
- **Triage operations** — labelling, archiving, marking read — under the mandate
  rule like any other write.

### Refused by the tool

Sending, and every settings operation. These are not in any allowlist, a
persistent per-account guard blocks sending independently, and the policy that
compiles into the binary can hold the same rule where no flag or environment
variable can lift it. An agent that receives a refusal reports it; it does not
look for another route.

## Known caveats

- The person's tokens live in their own state root. On a machine with a single
  operating-system account, separation between persons is organizational rather
  than enforced by the system — real isolation means separate machines or
  accounts.
- Google's authorization is a one-time human ceremony per account. Until it is
  done, every command fails for that account and the assistant says so instead
  of working around it.
- The exact flag spellings live in the tool's own help. This spec fixes what is
  permitted, not how the tool spells it.
