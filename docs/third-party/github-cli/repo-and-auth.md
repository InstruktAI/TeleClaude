---
description: GitHub CLI (gh) — auth status check and non-interactive repository creation for automated remote provisioning.
---

# GitHub CLI — Repo Creation and Auth

## Overview

`gh` is GitHub's official CLI. Two commands are used to provision a project's
remote automatically: an authentication probe and a repository-create that also
wires the local git remote. The CLI authenticates through the machine's existing
`gh` login — no token is read from or written to TeleClaude config.

## Availability and auth probe

- Presence: check `shutil.which("gh")`; absence means automation is unavailable
  and the caller falls back to a human step.
- Auth probe: `gh auth status --hostname <host>` exits `0` when the machine has a
  valid login for that host, non-zero otherwise. It writes human-readable status
  to stderr; callers branch on the exit code, not the text.
- Scope: repository creation requires the `repo` scope on the active login.

## Creating a repository and wiring the remote

`gh repo create` creates a repository and can configure the local git remote in
one step:

```
gh repo create <owner>/<name> --private --source <dir> --remote <name>
```

- `<owner>/<name>` — the target org/owner and repository name. Without an owner
  prefix the repo is created under the authenticated user.
- `--private` / `--public` / `--internal` — visibility. Exactly one applies;
  `--private` is the safe default for internal project work.
- `--source <dir>` — create from the existing local repository at `<dir>` and
  configure its remote (rather than cloning a fresh directory).
- `--remote <name>` — the git remote name to add (e.g. `origin`).
- `--push` — optional; pushes local commits to the new repository. Omit to
  create-and-wire without transferring history.

The command is non-interactive when all required values are supplied; it exits
non-zero on failure (already-exists, insufficient scope, network). It targets
`github.com` by default; non-GitHub hosts are not served by `gh repo create` and
require the human-fallback path.

## Sources

- https://cli.github.com/manual/gh_repo_create
- https://cli.github.com/manual/gh_auth_status
