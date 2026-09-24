---
activation_trigger: 'Use when macOS security or firewall prompts recur after rebuilding a locally built binary or app bundle, or when a build must carry a code identity that survives recompilation'
description: 'Give locally built macOS artifacts a code identity that survives rebuilds — one machine-local signing authority, a stable unique identifier per executable — so Full Disk Access and firewall grants outlive recompilation.'
visibility: 'public'
---

# macOS Stable Code Signing — Procedure

## Goal

A locally built macOS binary or app bundle presents the same code identity after every
rebuild, so grants the operating system attaches to it — Full Disk Access and other TCC
permissions, firewall rules, keychain access — keep matching instead of prompting again.

The operating system identifies a program by its signing authority together with its code
signing identifier. One machine-local authority is shared by every locally built artifact;
the identifier stays unique per executable, and each executable keeps its own grants.

## Preconditions

- The artifact is built on the machine that runs it, rather than distributed to others.
- The project exposes a build path that can run a signing step; a build invoked directly
  through the language toolchain bypasses it.

## Steps

1. **Ensure the machine's signing authority exists.** `security find-certificate -a -c
"<name>"` reports how many carry the name. A self-signed certificate chains to no trusted
   root, so it never appears among the _valid_ identities `security find-identity -v` lists,
   while `codesign` signs with it and the result verifies — detect the certificate, not its
   validity. When none exists, create a self-signed **Code Signing** certificate under that
   name. Create it once per machine and share it across projects: the name identifies it to
   humans, while the operating system matches the certificate itself. When more than one
   carries the name, signing is ambiguous — fail rather than pick one, and note that deletion
   by name is refused for the same reason and must address each certificate by fingerprint.
2. **Give the artifact a stable, unique identifier.** Pass `--identifier` with a reverse-DNS
   name the artifact keeps for its lifetime; for a bundle it is the declared bundle
   identifier, which an ad-hoc signature does not necessarily carry — a linker-produced
   signature can name the executable instead, so read the declared value rather than the
   current signature. A toolchain that signs automatically derives the
   identifier from the build and can embed a build-specific suffix, which changes across
   rebuilds exactly like the content hash does.
3. **Sign as part of the build:** `codesign --force --options runtime --timestamp=none
--identifier <reverse-dns-name> --sign "<authority>" <artifact>`, run from the project's
   build target immediately after the artifact is produced. `--force` replaces any existing
   signature, so repeating the step on an already-signed artifact is a no-op; omitting the
   trusted timestamp keeps the signature reproducible and the build free of a network call.
4. **Confirm the authority and identifier on every run.** `codesign --verify --strict` passes
   and `codesign -dvvv <artifact>` names the certificate as the authority and reports the
   chosen identifier. A linker-produced signature reports
   `Signature=adhoc`, carries no authority, and identifies the artifact by its content hash.
5. **Grant the operating system's permissions per executable.** Each executable earns its own
   Full Disk Access grant and its own firewall rules. A shared authority removes the repeated
   prompting; it never merges two programs into one grant, and it must not — an identifier
   shared between executables would let either inherit the other's permissions.
6. **Prove a grant survives.** Rebuild, re-sign through the same build path, and exercise the
   permission again. A grant that survives one rebuild survives all of them; a grant that does
   not means the operating system is matching something other than the signed identity, and
   that must be resolved before more grants are attached to it.

## Outputs

- A signing authority present in the machine's keychain, shared by every locally built artifact.
- A build path producing signed artifacts with stable per-executable identifiers, without a
  manual step.
- Operating-system grants that survive rebuilds, evidenced by a rebuild that prompted nothing.

## Recovery

- **Prompts return after a rebuild:** confirm the artifact is signed rather than ad-hoc, and
  that its identifier is the explicit one. A build invoked through the language toolchain
  directly skips the signing step and restores the content-derived identity.
- **The identifier must change:** re-sign before any grant is attached. Every grant is bound
  to the identity that existed when it was made, so changing an identifier afterwards voids
  them exactly as replacing the certificate does.
- **The authority is missing from the keychain:** a replacement certificate created under the
  same name is a different certificate, so every grant bound to the old one is void and must
  be reissued. Keep an export of the certificate and its private key where the machine's
  other credentials live, protected by a random passphrase held in the keychain rather than a
  chosen one, and prove the export is readable with that passphrase before relying on it.
- **The export cannot be produced from the keychain:** an import that granted key access to
  the signing tool alone leaves no other tool able to read it. Grant access to both the
  signing and the keychain tool at import, and keep the export made at creation time — that
  copy is the backup, and re-deriving one later depends on an access list that may forbid it.
- **A second machine needs the same authority:** import the exported certificate rather than
  creating a new one under the same name, so both machines present one authority.

## Discipline

This procedure is idempotent in its steps and not in its certificate. Re-running it against a
correctly signed artifact changes nothing; deleting and recreating the certificate breaks every
grant that referenced it, because the operating system remembers the certificate rather than
its name. Treat the authority as durable machine state: create it once, export it, never
recreate it casually. Identifiers stay distinct per executable, so authorizing one program
never authorizes another. A self-signed authority serves locally built artifacts; artifacts
distributed to machines you do not control need an issued developer identity instead, which is
a separate decision.

An unsigned artifact is identified by a hash of its executable and an ad-hoc one by a hash of
its code directory, so every rebuild presents a new program to anything that authorizes it. A
signed artifact is identified by its signing key and identifier, which a rebuild does not
change — which is why stable signing ends repeated prompting in permission systems and network
filters alike.

Separation between artifacts holds only where the identifier is part of that identity. A
permission system that stores the authority together with the identifier keeps every
executable distinct, so one machine-local authority stays safe there. A network filter that
derives identity from the signing key alone treats every artifact under one authority as one
program, and a rule written against that identity authorizes all of them; constrain each such
rule by executable path with identity checking, which keeps artifacts separate while still
tolerating rebuilds signed by the same key.
