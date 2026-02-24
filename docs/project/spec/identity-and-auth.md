---
id: 'project/spec/identity-and-auth'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for system-wide identity, authentication, and person management.'
---

# Identity and Auth — Spec

## Required reads

- @project/spec/teleclaude-config

## What it is

A unified identity model where authorized human users ("People") are defined in a centralized YAML configuration and authenticated via client-specific methods.

## Canonical fields

### Identity Source of Truth

The list of authorized users is defined in the `people` section of `teleclaude.yml`.

| Field   | Type   | Description                                           |
| ------- | ------ | ----------------------------------------------------- |
| `name`  | string | Display name used in UI and logs.                     |
| `email` | string | Canonical email address used for OTP authentication.  |
| `role`  | enum   | One of: `admin`, `member`, `contributor`, `newcomer`. |

### Web Authentication (NextAuth)

The Web Interface uses **NextAuth (v5 Beta)** with the following flow:

1. **Selection:** User selects their name from `/api/people` (which reads from YAML).
2. **OTP Delivery:** A 6-digit verification code is sent via `nodemailer` using the `SMTP_*` and `EMAIL_FROM` environment variables.
3. **Verification:** `NextAuth` verifies the code.
4. **Authorization:** The `signIn` callback ensures the email matches a `people` entry in `teleclaude.yml`.

### Client Mapping

- **TUI:** Operates under the current OS user context.
- **Telegram:** Maps User IDs to `Person` entries via metadata.
- **Web:** Maps authenticated Email sessions to `Person` entries.
