---
description: Claude Code native install and update lifecycle — installer endpoint, `claude update`, auto-update behavior, and channel/version controls.
---

# Claude Code — Install and Update Lifecycle

## Install (native installer)

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

- Accepts a channel or version argument: `| bash -s stable`, `| bash -s 2.1.89`.
  Default is the `latest` channel; the channel chosen at install time becomes
  the default for subsequent updates.
- Installs the binary to `~/.local/bin/claude` with version payloads under
  `~/.local/share/claude`. No sudo required.
- Alternative managed channels exist (Homebrew cask, WinGet, apt/dnf/apk,
  npm) — those are upgraded by their own package managers, not by
  `claude update`.

## Update

```bash
claude update
```

- "Check for updates and install if available" (also aliased `claude upgrade`).
  Applies an update immediately without waiting for the background check.
- Native installations additionally **auto-update in the background**: Claude
  Code checks on startup and periodically while running; updates take effect on
  next start. `claude doctor` shows the result of the most recent attempt.
- Controls:
  - `DISABLE_AUTOUPDATER=1` (env/settings) stops only the background check;
    `claude update` still works.
  - `DISABLE_UPDATES` blocks all update paths including manual.
  - `autoUpdatesChannel` setting: `latest` (default) or `stable` (~1 week
    delayed, skips major regressions).
  - `minimumVersion` setting pins a floor that both auto-updates and
    `claude update` refuse to go below.

## Non-interactive behavior

Both the installer and `claude update` run unattended in a pipe (no TTY
required). Exit-code semantics are not documented by the vendor; a non-zero
exit is the only reliable failure signal.

## Sources

- [Advanced setup — Install / Update Claude Code](https://code.claude.com/docs/en/setup)
