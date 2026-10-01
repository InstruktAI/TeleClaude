---
description: Every macOS launcher TeleClaude installs is signed by one stable machine signing authority, without waiting for a person, and a signing run that cannot finish leaves the installed launchers untouched.
visibility: internal
delivered_by:
  - unattended-launcher-signing
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
  key is authorized for unattended use by the signing tool. A self-signed
  authority is never in the system's trusted-identity list, and that is not a
  readiness failure. Any of these failing fails the run at
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
When signing or building the launcher set fails or times out
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

#### UC-LCI9: An install with nothing to rebuild does not sign

```gherkin
Given a machine whose installed launchers were built from the current launcher inputs and signed by its current signing authority
When the installer runs again, as an operator install or as post-commit maintenance for an unrelated change
Then it does not open the signing store and signs nothing
And every installed launcher is byte-identical to what it was before the run
```

#### UC-LCI10: A change to what a launcher is built from rebuilds the set

```gherkin
Given a machine whose installed launchers were built from earlier launcher inputs
When an agent runs the installer after any launcher input has changed
Then the launcher set is rebuilt, signed by the machine's signing authority and installed
```

#### UC-LCI11: An installation updating itself carries changed launchers along

```gherkin
Given an installation enrolled on a release channel, with no person present
When it updates itself to a release that changes what its launchers are built from
Then an operator inspecting the machine afterwards finds its installed launchers rebuilt from that release and signed by the machine's signing authority
```

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
