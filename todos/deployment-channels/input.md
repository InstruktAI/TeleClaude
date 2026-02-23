# Input: deployment-channels

## Context

Parent todo: `mature-deployment` (decomposed). Phase 2 of 5.
Depends on: `deployment-versioning`.

## Brain dump

Each computer subscribes to a deployment channel that determines what versions
it receives and how quickly.

### Channel model

- **Alpha** — follows `main` HEAD. Every push auto-deploys. Dev machines only.
- **Beta** — follows GitHub releases (minor + patch). CI passes, release created,
  beta subscribers auto-pull.
- **Stable** — pinned to a minor version, receives patches only. Moving to next
  minor requires explicit human decision.

### Config

Goes in `config.yaml` under a `deployment` key:

```yaml
deployment:
  channel: beta # alpha | beta | stable
  pinned_minor: '1.3' # only for stable channel
```

Default to `alpha` for backward compat during rollout.

### Version watcher

A script job (not agent — deterministic logic) in the cron runner:

- Runs every 5 minutes (matches cron interval)
- Alpha: `git ls-remote origin HEAD` vs current HEAD
- Beta: GitHub API latest release vs current version
- Stable: GitHub API latest patch in pinned minor vs current
- Writes signal file: `~/.teleclaude/update_available.json`

### Open questions

- Should Redis broadcast version-available for faster propagation? Or is polling
  sufficient? (Polling is simpler, Redis-independent)
