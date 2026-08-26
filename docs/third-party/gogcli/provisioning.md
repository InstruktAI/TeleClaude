---
description: 'gogcli (gog) — Google Workspace CLI: canonical repo, Homebrew tap behavior, goreleaser release layout, and the verified v0.38.1 provisioning facts (asset naming, Linux SHA-256 digests, version surface).'
---

# gogcli (gog) Provisioning Facts

## Overview

`gogcli` is "Google Workspace in your terminal" — a single-binary Go CLI installed as `gog`, covering Gmail (including send-as aliases) and Calendar among other Workspace surfaces.

- **Canonical repository:** `github.com/openclaw/gogcli`. The former address `github.com/steipete/gogcli` is a redirect to it; provisioning must address the canonical location.
- **Installed binary name:** `gog` (the formula and release tarballs both ship the binary as `gog`).
- **Version surface:** `gog --version` prints the build-injected version. The generated command docs (`docs/commands/gog-version.md`) additionally document `gog version` with `-j|--json|--machine` ("Output JSON to stdout (best for scripting)"), emitting a stable `version` field — the canonical scripting surface for version reads.

## Homebrew tap

- Tap: `openclaw/homebrew-tap`, formula `Formula/gogcli.rb` — install with `brew install openclaw/tap/gogcli` (brew resolves the tap inline).
- The formula installs **prebuilt per-OS/per-arch release tarballs** with formula-owned SHA-256 values, for both macOS (`darwin_amd64`, `darwin_arm64`) and Linux (`linux_amd64`, `linux_arm64`). It does **not** build from source, so no Xcode Command Line Tools requirement applies. Verified directly against the formula content at research time (2026-08-26, formula at v0.38.1).

## Release layout (goreleaser)

Each GitHub release at `github.com/openclaw/gogcli/releases` ships:

- `gogcli_<version>_darwin_{amd64,arm64}.tar.gz`
- `gogcli_<version>_linux_{amd64,arm64}.tar.gz`
- `gogcli_<version>_windows_{amd64,arm64}.zip`
- `checksums.txt` — SHA-256 per asset
- `SIGNING-MANIFEST.json`, `ASSET-INVENTORY.json`, `RELEASE-NOTES.md`

Download URL shape: `https://github.com/openclaw/gogcli/releases/download/v<version>/gogcli_<version>_linux_<arch>.tar.gz`.

## Verified pin — v0.38.1 (research date 2026-08-26)

Latest release at research time: **v0.38.1**. Linux tarball SHA-256 digests, read from the release's `checksums.txt`:

| Asset                              | SHA-256                                                            |
| ---------------------------------- | ------------------------------------------------------------------ |
| `gogcli_0.38.1_linux_amd64.tar.gz` | `6576828ed6852949ba424b967c3ff4268b3d9c90e201f90fe3d539fe3a151ebb` |
| `gogcli_0.38.1_linux_arm64.tar.gz` | `462342542472dcf361744cfe5e15a3540364b4c5120577e4519fffbd1afc6596` |

## Configuration surface

Upstream documents account/credential configuration (OAuth setup, the `GOG_HOME` directory) separately from binary installation; installing the binary performs no account setup.

## Sources

- https://github.com/openclaw/gogcli — canonical repository (redirect target of steipete/gogcli)
- https://raw.githubusercontent.com/openclaw/gogcli/main/docs/install.md — install docs, version surface, asset naming
- https://raw.githubusercontent.com/openclaw/homebrew-tap/main/Formula/gogcli.rb — formula content (prebuilt tarballs, `bin.install "gog"`)
- https://github.com/openclaw/gogcli/releases/download/v0.38.1/checksums.txt — v0.38.1 digests
- https://api.github.com/repos/openclaw/gogcli/releases/latest — release inventory at research time
