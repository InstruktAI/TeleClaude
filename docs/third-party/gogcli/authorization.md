---
description: 'gogcli (gog) authorization: the one-time Google Cloud ceremony, the per-person state root, the narrow-scope invocation that avoids the Gmail settings scopes, and the verification and failure surface at v0.38.1.'
---

# gogcli (gog) Authorization Facts

## Overview

Google authorization for `gog` is a one-time human ceremony per Google Cloud
project, followed by a one-time browser consent per account. An OAuth client
identifies the application rather than a person: every account that consents
against a client receives its own refresh token, stored under whichever gog
state root was active at the time.

Facts below were read from the gogcli source at commit `324f656a`, which is the
build hash of the installed `v0.38.1` binary, and from the upstream quickstart.

## The one-time console ceremony

`gog auth setup` is a guided printer, not an installer. Without
`--create-project`, `--enable-apis`, or `--credentials` it emits instructions and
URLs and performs no work. Five steps happen in the Google Cloud console; only
the first two have any `gcloud` automation behind them, and no gog flag replaces
the remaining three:

1. **Create a project** — `console.cloud.google.com/projectcreate`.
2. **Enable the APIs** — the API Library. For mail and calendar these are
   `gmail.googleapis.com` and `calendar-json.googleapis.com`.
3. **Configure the consent screen** — `console.cloud.google.com/auth/branding`.
   External user type with the operator's own address is sufficient for personal
   use.
4. **Create a Desktop app OAuth client and download its JSON** —
   `console.cloud.google.com/auth/clients`. Desktop type matters: the browser
   flow redirects to `http://127.0.0.1:<ephemeral-port>/oauth2/callback`, and
   loopback redirects on a Desktop client need no registered redirect URI. The
   ceremony never asks the human to type one.
5. **Publish the app** — `console.cloud.google.com/auth/audience`, Publish app,
   then Confirm. This moves the app to production and does **not** submit it for
   verification. Skipping it leaves the app in Testing, where refresh tokens
   expire after seven days.

### gcloud is not worth installing for this

`gog auth setup` shells out to `gcloud` for exactly two operations:
`gcloud projects create` under `--create-project`, and `gcloud services enable`
under `--enable-apis`. Both are one-time console clicks. gcloud automates none
of the consent screen, the client creation, the JSON download, or the publish
step, and it introduces `gcloud auth login` as its own prerequisite. Absent
gcloud, gog states the substitution itself: `Install gcloud, or create/select a
Google Cloud project manually`.

## The per-person state root

`--home` is a global flag on every command, equivalent to `GOG_HOME`. It must be
absolute; a relative value fails with `path must be absolute`. The layout beneath
it is `config/`, `data/`, `state/`, `cache/`, and the ingested OAuth client lands
at `<home>/data/credentials.json`.

`--home` isolates configuration and credentials. Whether it isolates **secrets**
depends on the keyring backend, and this is the trap:

- With the `file` backend, secrets live at `<home>/data/keyring` and isolation is
  complete.
- With `auto` or `keychain` on macOS, the keyring service name is the constant
  `gogcli`, derived from neither the home nor the person. Every home shares one
  keychain namespace and can read every other home's tokens. Token keys are
  `token:<client>:<email>`, so distinct addresses do not collide — but they are
  not walled off from each other either.

Real isolation between people sharing one operating-system account therefore
requires `GOG_KEYRING_BACKEND=file` with a distinct `GOG_KEYRING_PASSWORD` per
person. Where each person has their own OS account, `--home` with the default
keychain is sufficient.

## Authorizing one account

```
export GOG_HOME=/absolute/path/to/people/<slug>
gog auth credentials set /absolute/path/to/client_secret_XXXX.json
gog auth add <email> --services calendar --extra-scopes https://www.googleapis.com/auth/gmail.modify
```

The client secret is stored in the keyring rather than in `credentials.json`
unless `--insecure` is passed.

### `--services` defaults to everything

Omitting `--services` requests `user`, which resolves to the full union of every
default user service and its scopes. It is always passed explicitly.

### The narrow invocation, and why it is shaped that way

`--gmail-scope` offers `full`, `readonly`, `send`, and `read-send`. Only `full`
carries `gmail.modify`, and it hard-codes `gmail.settings.basic` and
`gmail.settings.sharing` alongside it — the latter covering delegates, send-as,
and forwarding. The three modes that exclude the settings scopes all also exclude
`gmail.modify`, and so cannot label or archive. There is no mode yielding
`gmail.modify` alone.

Requesting `gmail.modify` through `--extra-scopes` instead of through
`--services gmail` sidesteps this. Extra scopes are appended unconditionally
without requiring service membership, and gog's ordinary Gmail client is built
without a stored-grant check, so it does not verify that the grant contains its
nominal Gmail scope triple. The resulting grant is `calendar`, `gmail.modify`,
and the three OIDC scopes, and nothing else.

`gmail.modify` alone is sufficient for reading, labelling, archiving, drafting,
and sending: `users.messages.send` accepts it. Nothing broader is needed.

Two consequences to expect. `gog gmail batch delete` fails against this grant,
since it requires `https://mail.google.com/`. Settings **reads** do not fail:
`gog gmail settings filters list` and the delegates listing both succeed, because
those API methods accept `gmail.modify`. Only settings writes are refused. And
the stored token's service list reads `calendar`, which is cosmetic but appears
in gog's re-authorization hint, so that hint will suggest a command missing
Gmail.

This shape is confirmed against a live account, not only against source: an
authorization performed with the invocation above produced exactly profile info,
`gmail.modify`, and full calendar in Google's own per-app permission record, with
no settings scope of either kind.

### Confirming the narrow grant took

Read the granted scopes directly; do not infer them from a command failing.
Google records them per authorized app at `myaccount.google.com/permissions`. A
correct narrow grant lists profile info, "Read, compose, and send emails from
your Gmail account" — Google's own wording for `gmail.modify` — and full
calendar access. It names no settings, filters, forwarding, or send-as
identities.

A failure-based probe does not work for this boundary, and reaching for one
produces a false result. Gmail's settings **read** methods accept `gmail.modify`
as a valid scope: `users.settings.filters.list` and
`users.settings.delegates.list` each list it alongside `gmail.settings.basic`,
so both succeed under a correct narrow grant and prove nothing about the
settings scopes. Only settings **writes** require `gmail.settings.basic` or
`gmail.settings.sharing`, and exercising a write to test whether it is forbidden
crosses the gate being verified.

`gog gmail labels list` remains worth running to confirm the grant functions at
all. Its success establishes that Gmail access works; it establishes nothing
about scope width.

## Verification

```
gog auth list --check
gog auth doctor --check
gog -a <email> auth status
```

`--check` is what contacts Google; without it these commands report local state
only. `gog auth status` prints the account block **only** when an account
resolves, so without `-a` or `GOG_ACCOUNT` it reports nothing about whether
authorization succeeded. `doctor` reports the worst status across all its checks,
and an unauthorized machine shows `warn tokens no OAuth tokens stored`. Exit code
`4` is the authorization failure code.

## Known caveats

- **Re-consent cannot narrow an existing grant; only revocation can.** The
  authorization URL carries `include_granted_scopes=true`, so a second consent
  is additive to whatever the account already granted. Re-authorizing with a
  narrower scope leaves the wider one in place and adds the narrower beside it.
  To drop a scope, the human removes the app's access at
  `myaccount.google.com/permissions` and authorizes again from clean, where
  additive-to-nothing is exact.
- **An unticked consent checkbox mints a valid token that can do nothing.**
  Google's consent screen presents a checkbox per permission. Boxes left
  unticked still produce a working refresh token: `gog auth doctor --check`
  reports `status ok` and the refresh exchange succeeds, while every call needing
  a permission that was left unticked returns `403 insufficientPermissions`.
  Observed with one permission ticked and another not: calls under the granted
  one worked while calls under the ungranted one failed, so a partial consent
  presents as a healthy account with one surface silently dead. gog detects the 403, refreshes, and
  retries once — which cannot help, because a refresh never widens a token's
  scopes. Verify against the permissions page, not against the doctor.
- **gog cannot use a narrowed calendar scope.** There is a `--gmail-scope` flag
  but no calendar equivalent, and supplying `calendar.events` through
  `--extra-scopes` does not work: with that scope granted at the account level
  and confirmed on the permissions page, `gog calendar events <id>` still
  returns `403 insufficientPermissions`, including after gog's own
  refresh-and-retry. `calendar.events` is a documented valid scope for
  `events.list`, which points at gog rather than Google as the constraint. That
  attribution is inferred from the probe, not read from gog's source, and it is
  the one claim here that has not been verified at its cause. Calendar
  therefore requires `--services calendar`, which grants full calendar access —
  seeing, editing, sharing, and permanently deleting calendars. Narrowing that
  surface has to be done by disabling commands rather than by scope.

- **`--force-consent` adds `prompt=consent`** and is the recovery for a token
  issued while the app was still in Testing, after publishing it.
- **`invalid_grant`** means the refresh token was revoked, expired, or blocked by
  app policy. gog can relaunch the browser flow automatically, but only in an
  interactive session; under `--no-input` or a non-TTY it is a hard failure by
  design, which is the correct behavior for an unattended run.
- **The file keyring needs `GOG_KEYRING_PASSWORD` in any non-interactive
  process.** A command succeeding in a login shell proves only that the shell
  has the password, not that a service or agent subprocess inherited it.
- **macOS keychain prompts** can stall the first read; gog's own guidance is to
  run an authorizing command from an interactive terminal once and accept the
  permission prompt.
- **Runtime guards compose on top of scope.** `--gmail-no-send` blocks send
  operations, `--disable-commands` takes dot paths such as `gmail.settings`, and
  a safety-profile build compiles the command policy into the binary where no
  flag or environment variable can lift it.

## Sources

- https://github.com/openclaw/gogcli/commit/324f656a
- https://gogcli.sh/commands/gog-auth.html
- https://github.com/openclaw/gogcli/blob/main/docs/quickstart.md
- https://github.com/openclaw/gogcli/blob/main/docs/auth-clients.md
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send
