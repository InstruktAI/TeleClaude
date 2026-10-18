---
description: Every macOS launcher TeleClaude installs is signed by one stable machine
  signing authority, without waiting for a person, and a signing run that cannot finish
  leaves the installed launchers untouched.
visibility: internal
---

# Launcher Code Identity — Spec

## What it is

On macOS, every machine installs its own launcher apps through which its agents and tmux
reach protected files. macOS grants Full Disk Access to a launcher's code
identity — its signing authority together with its identifier — so the identity
a launcher presents is machine state an operator has granted against, per
`sdlc/procedure/macos-stable-code-signing`.

Installation produces that identity on the machine it runs on. Every route
that builds and installs launchers — the machine's own post-commit maintenance
or self-update, an operator's install, a manual launcher rebuild, a recovery
session on the machine — signs through the same installation-owned path, and that path never
waits for a person: with no terminal, no one at the screen and no graphical
login, it either signs every launcher or fails within a bounded time, naming
what failed and how to resolve it.

The machine keeps one signing authority in a signing store dedicated to
launcher signing. Installation creates the authority once, when that store
holds none, and from then on signs with that same authority on every run, so
Full Disk Access grants survive every rebuild. Installed launchers are replaced
only by a complete, verified set; a signing or build failure or timeout leaves
the launchers already installed exactly as they were.

Signing establishes code identity only. It never grants Full Disk Access or any
other permission; granting stays with a person or a managed device profile.

## Canonical fields

- **Signing authority.** The machine's one certificate and private key that
  sign every launcher. It is identified by its fingerprint, never by its name:
  another certificate carrying the same name is not this authority. Each
  machine creates its own authority; it is never imported from another machine
  or shared with one.
- **Signing store.** The keychain that holds the signing authority and nothing
  the operator uses for anything else. A signing run unlocks it for a bounded
  window that covers that run, after which it locks again on its own.
- **Step deadlines.** Every keychain-tool invocation and every code-signing-tool
  invocation in a signing run — whether it signs, verifies or inspects a
  signature — carries its own deadline, independent of the store's unlock
  window. A step that reaches its deadline fails the run.
- **Unlock secret.** The secret that opens the signing store. Installation
  generates it on the machine itself; it is never provisioned from outside or
  carried to or from another machine. It
  is readable by installation and maintenance after logout or reboot, is never
  stored inside the store it opens, and never appears in output, logs or a
  repository. It protects the store from other operating-system users, not
  from the user TeleClaude runs as.
- **Launcher set.** Every launcher the installed agent registry and tmux
  require. A launcher set is complete when each launcher carries a valid
  strict signature by the signing authority and its own stable identifier.
- **Launcher inputs.** Everything a launcher is built from: its source, the
  per-launcher configuration the build derives, and the agent roster that
  decides which launchers exist. A run rebuilds, re-signs and redeploys the
  launcher set only when those inputs changed since the installed launchers
  were built, when an installed launcher is missing or does not match what the
  inputs produce, or when the signing authority is new. Otherwise it neither
  opens the signing store nor signs, and leaves the installed launchers
  untouched.
- **Unattended readiness.** Before signing, a run confirms that the signing store
  opens, the authority is present with its private key and not expired, and its
  key is authorized for unattended use by the signing tool. Readiness does
  not depend on whether the system trusts the authority; trust is a separate,
  policy-specific setting. Any of these failing fails the run at
  once, naming the cause; signing never relies on a prompt.
- **Authority creation.** Happens only when the signing store holds no
  authority. A store that is locked is opened with the unlock secret and signs
  as usual. A store that cannot be opened, an unavailable or rejected unlock
  secret, a signing run that runs out of time, or a launcher set that fails
  verification never causes a new authority to be created; each fails the run
  instead. Deliberately
  replacing an authority remains a separate operator act outside installation;
  it voids every grant bound to the old authority
  (`sdlc/procedure/macos-stable-code-signing`).
- **Outcome report.** A successful run states the authority it signed with and
  whether it created that authority in this run. A run that created a new
  authority while launchers signed by a different authority were installed
  states that those launchers' Full Disk Access grants must be granted again.

### Use cases

#### UC-LCI1:

```gherkin
Scenario: An operator installs launchers unattended with the machine's stable identity
Given a macOS operator needs TeleClaude launchers installed or updated on a machine with Full Disk Access grants
When the installation runs without a person at the screen
Then every launcher is installed with the machine's stable signing identity
And the run completes without prompting for input
And the installer reports whether it established a new identity
And if launchers signed by another identity were already installed, it says their Full Disk Access grants must be renewed

Scenario: An unattended update cannot leave a partial launcher set installed
Given launchers are installed and in use
When the new launcher set cannot be built, signed, or verified within the run's bound
Then every installed launcher remains as it was before the run
And the installer reports the failure and how to resolve it
```

#### UC-LCI2:

#### UC-LCI3:

#### UC-LCI4:

#### UC-LCI5:

#### UC-LCI6:

#### UC-LCI7:

#### UC-LCI8:

#### UC-LCI9:

#### UC-LCI10:

#### UC-LCI11:

## Known caveats

- The unlock secret is protected by the operating system's per-user file
  permissions. A process running as the same user can read it, consistent with
  the platform's same-user trust boundary.
- Full Disk Access remains a separate, operating-system-owned grant. A machine
  whose launchers have never been granted it signs and installs successfully
  and still lacks that access. Granting it needs a person at that machine's
  screen, so a recovery session that creates a new authority restores signing
  but leaves the re-grant owed.
- Launchers exist on macOS only; other platforms install no launchers and are
  outside this contract.

## See Also

- ~/.teleclaude/docs/sdlc/procedure/macos-stable-code-signing.md — why a launcher's authority and identifier must outlive rebuilds.
- docs/local/spec/feature/reconciliation/launch-service-installation.md — the launch units installation deploys beside the launchers.
