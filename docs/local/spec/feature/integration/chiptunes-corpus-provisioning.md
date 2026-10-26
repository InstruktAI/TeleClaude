---
description: With chiptunes enabled, the daemon installs the HVSC music corpus into an empty music directory from the one archive its shipped manifest pins, and refuses a download that does not match the pinned checksum.
---

# Chiptunes Corpus Provisioning — Spec

## What it is

The chiptunes player (`local/projects/teleclaude/spec/domain/integration`)
plays tunes from the High Voltage SID Collection (HVSC) in its music directory.
A release ships without that corpus. The daemon installs it on demand, so a
fresh installation with chiptunes enabled gets its music without a manual
download.

## Canonical fields

- **Trigger.** Daemon startup and a chiptunes configuration reload, when
  chiptunes is enabled and the selected music directory is absent or empty. A
  populated directory is used as it is and never downloaded again; a disabled
  configuration downloads nothing.
- **Music directory.** The configured chiptunes music directory, otherwise the
  default corpus directory inside the active release.
- **Pinned archive.** One HVSC release archive, identified by the version,
  address and SHA-256 in the manifest shipped with the code
  (`teleclaude/chiptunes/hvsc_manifest.json`). The download runs in the
  background and does not hold up the daemon.
- **Integrity.** The downloaded archive is hashed and compared with the pinned
  SHA-256 before anything is extracted. A mismatch is refused, logged as an
  error with both digests and the address, and leaves the music directory
  untouched.
- **Outcome.** On success the archive is extracted into the music directory and
  the player activates. When the manifest cannot be read, the download fails,
  the checksum is refused, or extraction fails, the player stays inactive, the
  daemon logs a warning naming the failure, and the daemon keeps serving.

- **Repair pointer.** A failed download and a refused checksum are each logged
  with the manifest file the pin is read from and the HVSC downloads page that
  lists current releases, so the reader of the log has both at hand.

## Known caveats

- **One source.** Provisioning fetches from the single pinned address and has
  no fallback. When that host stops serving the pinned archive, every fresh
  installation runs with chiptunes enabled and no corpus until the manifest's
  version, address and checksum are updated.
- **Where current releases are listed.** The HVSC downloads page,
  <https://www.hvsc.c64.org/downloads>, lists the current release and its
  mirrors. It renders its links with JavaScript, so a plain HTTP fetch returns an
  empty page shell. HVSC mirror directories, such as
  <https://hvsc.brona.dk/HVSC/>, list every release archive as plain links. A
  replacement's SHA-256 comes from hashing the downloaded archive itself.
