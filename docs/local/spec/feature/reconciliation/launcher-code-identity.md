---
description: Every macOS launcher TeleClaude installs is signed by one stable machine signing authority, without waiting for a person, and a signing run that cannot finish leaves the installed launchers untouched.
visibility: internal
delivered_by:
  - unattended-launcher-signing
---

# Launcher Code Identity — Spec

## What it is

On macOS, TeleClaude installs launcher apps through which its agents and tmux
reach protected files. macOS grants Full Disk Access to a launcher's code
identity — its signing authority together with its identifier — so the identity
a launcher presents is machine state an operator has granted against, per
`sdlc/procedure/macos-stable-code-signing`.

Installation produces that identity. Every route that builds and installs
launchers — an operator's install, post-commit maintenance, a manual launcher
rebuild — signs through the same installation-owned path, and that path never
waits for a person: with no terminal, no one at the screen and no graphical
login, it either signs every launcher or fails within a bounded time, naming
what failed and how to resolve it.

The machine keeps one signing authority in a signing store dedicated to
launcher signing. Installation creates the authority once, when that store
holds none, and from then on signs with that same authority on every run, so
Full Disk Access grants survive every rebuild. Installed launchers are replaced
only by a complete, verified set; a run that fails for any reason leaves the
launchers already installed exactly as they were.

Signing establishes code identity only. It never grants Full Disk Access or any
other permission; granting stays with a person or a managed device profile.

## Canonical fields

- **Signing authority.** The machine's one certificate and private key that
  sign every launcher. It is identified by its fingerprint, never by its name:
  another certificate carrying the same name is not this authority.
- **Signing store.** The keychain that holds the signing authority and nothing
  the operator uses for anything else. A signing run unlocks it for a bounded
  window that covers that run, after which it locks again on its own.
- **Step deadlines.** Every keychain-tool invocation and every code-signing-tool
  invocation in a signing run — whether it signs, verifies or inspects a
  signature — carries its own deadline, independent of the store's unlock
  window. A step that reaches its deadline fails the run.
- **Unlock secret.** The machine-local secret that opens the signing store. It
  is readable by installation and maintenance after logout or reboot, is never
  stored inside the store it opens, and never appears in output, logs or a
  repository. It protects the store from other operating-system users, not
  from the user TeleClaude runs as.
- **Launcher set.** Every launcher the installed agent registry and tmux
  require. A launcher set is complete when each launcher carries a valid
  strict signature by the signing authority and its own stable identifier.
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

#### UC-LCI1: An install with no one present signs every launcher without a dialog

```gherkin
Given a macOS machine whose signing store holds the signing authority and whose unlock secret is available
And no terminal, no graphical login and no person at the screen
When an agent runs the installer
Then every launcher in the launcher set is signed by the signing authority and installed
And no macOS dialog is raised and nothing waits for a person
And the installer states which authority it signed with
```

#### UC-LCI2: A repeat install keeps the same authority

```gherkin
Given a machine whose launchers were installed and signed by its signing authority
And the signing store has locked again since, after logout or reboot
When an agent runs the installer again
Then the launchers are signed by the same authority as before
And no new authority is created
```

#### UC-LCI3: The first install on a machine without an authority creates it once

```gherkin
Given a macOS machine whose signing store holds no signing authority
And launchers signed by a different authority may already be installed
When an agent runs the installer with no person present
Then the installer creates one signing authority in the signing store and signs every launcher with it
And it states that it created the authority
And where launchers signed by a different authority were installed, it states that their Full Disk Access must be granted again
```

#### UC-LCI4: A failed signing run leaves the installed launchers untouched

```gherkin
Given a machine with launchers installed and in use
When a signing run fails for any reason
Then every installed launcher is byte-identical to what it was before the run
And the installer exits unsuccessfully with a message naming what failed and how to resolve it
```

#### UC-LCI5: A signing step that cannot finish fails instead of waiting

```gherkin
Given a signing step that cannot complete, because the signing store cannot be opened or a signature does not finish
When an agent runs the installer with no person present
Then the run fails within a bounded time instead of waiting for input
And the installed launchers are left as they were
```

#### UC-LCI6: An unusable authority is never replaced by a new one

```gherkin
Given a machine whose signing store holds the signing authority
And the store cannot be opened because its unlock secret is unavailable or rejected
When an agent runs the installer
Then the run fails and names the unavailable unlock secret as the cause
And the signing store still holds the same authority and no other
```

#### UC-LCI7: A launcher set that fails verification is never installed

```gherkin
Given a rebuilt launcher set in which any launcher lacks a strict signature by the signing authority or carries an identifier other than its own
When the installer prepares to replace the installed launchers
Then it installs none of the rebuilt launchers
And it exits unsuccessfully naming the launcher and the mismatch
```

#### UC-LCI8: Every route that builds launchers signs through the same path

```gherkin
Given a machine whose launchers were installed and signed by its signing authority
When an operator rebuilds the launchers manually, or post-commit maintenance reinstalls them, with no person present
Then the launchers are signed by the same authority without a dialog
```

## Known caveats

- The unlock secret is protected by the operating system's per-user file
  permissions. A process running as the same user can read it, consistent with
  the platform's same-user trust boundary.
- Full Disk Access remains a separate, operating-system-owned grant. A machine
  whose launchers have never been granted it signs and installs successfully
  and still lacks that access.
- Launchers exist on macOS only; other platforms install no launchers and are
  outside this contract.

## See Also

- ~/.teleclaude/docs/sdlc/procedure/macos-stable-code-signing.md — why a launcher's authority and identifier must outlive rebuilds.
- docs/local/spec/feature/reconciliation/launch-service-installation.md — the launch units installation deploys beside the launchers.
