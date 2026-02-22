# Input: mature-deployment

## Brain dump

Current `teleclaude deploy` is primitive: `git pull + restart` on all connected
computers. No versioning, no channels, no migration support. Just yolo-pull main.

### What we want

**Channel-based deployment subscription model:**

- **Alpha** — follows `main`. Every push auto-deploys. Only dev machines subscribe
  to this. This is what the primary dev machine already does.

- **Beta** — follows GitHub releases (minor + patch). CI passes, release is created,
  beta subscribers auto-pull. Breaking changes (minors) are allowed because every
  release ships with migration manifests that auto-reconcile.

- **Stable** — pinned to a minor version, receives patches only. Machine stays on
  e.g. v1.3.x, auto-receives v1.3.1, v1.3.2. Moving to v1.4.x requires explicit
  human decision (bump the pin). This is the safety valve.

### Channel subscription

Goes into the computer's `config.yaml`. Each computer declares which channel
it subscribes to:

```yaml
deployment:
  channel: beta # alpha | beta | stable
  # Only for stable channel: which minor to pin to
  # pinned_minor: "1.3"
```

### Migration manifests — the key innovation

Every minor release includes numbered, ordered, idempotent migration steps.
Like database migrations but for config, schema, services. The deploy script
diffs current version vs target version and runs migrations in sequence.

The paradigm shift: breaking changes are NOT flagged as "breaking" in the
traditional sense. Instead, every release that introduces incompatibilities
also ships the reconciliation scripts to resolve them automatically. No human
in the loop, no manual steps, no "please run these commands after upgrading."

This is the holy grail: demonstrate that breaking changes can be self-healing
if the release pipeline is disciplined enough to include patching/migration
alongside every incompatible change.

### CI/release pipeline integration

- GitHub Actions CI is thorough and creates releases automatically
- Patch releases trigger beta + stable deployments
- Minor releases trigger beta deployments (stable stays pinned)
- Each release is a GitHub release with the migration manifest attached
- `telec deploy` becomes idempotent: checks channel subscription, checks
  available version, pulls if newer, runs migrations, restarts

### Open questions

- Where exactly does channel config live? `config.yaml` seems right.
- How do migration manifests get authored? Part of the PR process?
  (e.g. `migrations/v1.3.0/` directory with ordered scripts)
- How does rollback work? If a migration fails mid-way?
- Should alpha channel use releases too, or literally follow main HEAD?
- How does the dev machine (alpha) handle the fact that main may have
  commits that haven't been released yet? That's fine — alpha is by
  definition "whatever is on main."

### What this replaces

The current `teleclaude__deploy` MCP tool / `telec deploy` command which
just does `git pull + restart` via Redis transport to all connected computers.
