---
description: Codex CLI install and update lifecycle — installer endpoint, `codex update` self-update, and install-method caveats.
---

# Codex CLI — Install and Update Lifecycle

## Install

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh
```

- The installer endpoint above is the one TeleClaude's installer uses today;
  `CODEX_NON_INTERACTIVE=1` suppresses prompts for unattended runs.
- Officially documented alternatives: npm (`@openai/codex`), Homebrew, and
  standalone prebuilt binaries from GitHub Releases (static Rust binary, no
  Node.js requirement). Package-manager installs are upgraded by their own
  package manager.

## Update

```bash
codex update
```

- Vendor reference: "Check for and apply a Codex CLI update when the installed
  release supports self-update. Debug builds print a message telling you to
  install a release build instead."
- Self-update support depends on the installation method; release builds
  installed via the standalone/native path self-update in place.
- Verified against the installed CLI: `codex update` exists and accepts the
  global `-c/--config`, `--enable`, `--disable` overrides; no update-specific
  flags are documented in `--help`.

## Non-interactive behavior

`codex update` runs unattended (no TTY required). Exit-code semantics are not
documented by the vendor; a non-zero exit is the only reliable failure signal.

## Sources

- [Codex CLI](https://developers.openai.com/codex/cli)
- [Developer commands reference (`codex update`)](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
