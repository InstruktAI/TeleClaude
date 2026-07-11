---
description: Antigravity CLI (agy) install and update lifecycle — installer endpoint and the `agy update` self-updater.
---

# Antigravity CLI (agy) — Install and Update Lifecycle

## Install

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

- Official shell installer for macOS and Linux; runs unattended in a pipe.

## Update

```bash
agy update
```

- Vendor documentation: `agy update` "checks for newer versions and then
  downloads and updates your current local installation."
- Verified against the installed CLI: `agy update` takes no update-specific
  flags. `agy changelog` prints release notes.

## Non-interactive behavior

Both the installer and `agy update` run unattended (no TTY required).
Exit-code semantics are not documented by the vendor; a non-zero exit is the
only reliable failure signal.

## Sources

- [Antigravity CLI Overview](https://antigravity.google/docs/cli-overview)
- [Using AGY CLI](https://antigravity.google/docs/cli-using)
