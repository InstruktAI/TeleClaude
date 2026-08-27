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

Two consequences to expect. `gog gmail settings *` and `gog gmail batch delete`
fail against this grant, which is the intended outcome. And the stored token's
service list reads `calendar`, which is cosmetic but appears in gog's
re-authorization hint, so that hint will suggest a command missing Gmail.

### Confirming the narrow grant took

```
gog gmail labels list                 # must succeed
gog gmail settings filters list       # must fail
```

The second command establishes that the settings scopes are absent in exactly
one case: Google answered with a recognised insufficient-scope denial. gog's
transport identifies those specifically, matching Google's `insufficient
authentication scopes`, `insufficientPermissions`, and `access token scope
insufficient` responses, and retrying once after a token refresh before
reporting.

Every other failure is inconclusive and leaves the grant unknown. gog can block
`gmail.settings` locally through `--disable-commands` or a safety-profile build,
and such a refusal never reaches Google at all; equally, Google may refuse
because the Gmail API is not enabled on the project, or because of an account or
policy restriction. None of those say anything about what was granted, so the
probe is run against a build carrying no local guard over that surface, and its
result is read from the error rather than from the exit status.

That the narrow grant drives gog's Gmail client successfully is established as
far as gog's own code goes; Google's response to a `gmail.modify`-only grant is
what this probe confirms rather than assumes.

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

- **Re-consent replaces rather than adds.** Any narrowed grant disables
  `include_granted_scopes`, so a re-run must name every service and scope
  wanted, not only the new one.
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
