---
description: Kimi Code install channels and observed 0.37.2 native-binary update surface.
---

# Kimi Code Install and Update

## Installed reality

The inspected runtime is Kimi Code 0.37.2 at the configured Kimi home binary
location. It is not discoverable through this shell's `PATH`, so this
installation must be invoked by its absolute binary path. `kimi upgrade` and
its `update` alias are present and accept no update-specific options in the
installed help.

The installed configuration also has an `[upgrade]` section with an
`auto_install` setting. No update was run, because upgrade replaces the runtime
binary and would mutate the installed state.

## Vendor installation channels

The vendor documents a macOS/Linux install script and global npm or pnpm
packages. It says the install script checks the release checksum and places the
binary on `PATH`; that expected behavior does not hold for the inspected shell.
The vendor also documents `kimi upgrade` as the interactive update path, with
package-manager installations updated by their respective package manager.

## Gaps

- The installation method and any updater provenance of the inspected binary
  were not established.
- Upgrade and automatic-install behavior were not exercised.

## Sources

- https://moonshotai.github.io/kimi-code/en/guides/getting-started.html
- https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html
