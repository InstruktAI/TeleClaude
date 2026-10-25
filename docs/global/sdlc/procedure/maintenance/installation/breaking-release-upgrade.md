---
description: "Carry a published release that crosses an installation's compatibility series into that installation: perform its upgrade instructions in order, install it, verify it, and involve a person only for what only a person can supply."
visibility: 'public'
delivered_by:
  - channel-activation-on-green
---

# Breaking Release Upgrade — Procedure

## Goal

Bring the release the installation holds — a published release beyond its
active release's compatibility series, which the installation never installs on
its own — into the installation, on the installation's own computer, whether or
not a development checkout exists there. A person is asked only for what only a
person can supply (`general/policy/human-contract`).

## Preconditions

- The installation inspector's held-release route loaded this procedure for a
  held-release event that names the followed source and the release's version.
- `telec app status` names the active release, the channel and the held
  release.
- `telec app install`, `telec app status`, `instrukt-ai-logs` and
  `telec message` are available.

## Steps

1. **Confirm the hold is current.** Read `telec app status`. When the active
   release is already at or beyond the held release, or no release is held,
   the event is satisfied.
2. **Read the upgrade instructions.** Read the repository's upgrade guide —
   `UPGRADING.md` at the repository root — at the held release's revision in
   the installation's kept repository, together with the release's published
   notes. Collect the guide's section for every version between the active
   release and the held release, oldest first. A release whose guide carries no
   section for the versions it crosses requires no step beyond the install.
3. **Perform the steps in their stated order.** Each step that changes state
   outside the install act — a backup, a conversion, a setting — is carried out
   and checked before the next begins. Configuration changes go through
   `telec config`, never by editing the installed release.
4. **Ask for what only a person can supply.** When a step needs a credential,
   an outside account or a decision that is a person's own, send one message
   through `telec message` that names exactly what is needed and why. End the
   turn with the session open: the answer resumes the upgrade at the step that
   needed it, and other events the inspector answers are handled as they arrive.
   The installation keeps running its active release meanwhile. Nothing else is
   asked.
5. **Install.** Run `telec app install` with the held release's version. The
   install act prepares, migrates, switches and verifies, and reports every
   failure outcome through `telec app status`.
6. **Verify.** Read `telec app status` and the logs from the install onwards.
   The upgrade is complete when the installation serves the held release and
   the hold is cleared.

## Outputs

- The installation runs the held release, with every upgrade step performed;
  or the upgrade waits on a person's answer with what it needs stated; or it
  states why the install failed and what it left.

## Recovery

- **A step fails before the install.** Nothing has been installed; repair the
  step and continue from it.
- **The install fails without having migrated state.** The previously active
  release is serving again; repair the cause and install again.
- **The install fails after migrating state.** The daemon stays stopped with
  the stores that changed named in `telec app status`; repair forward and
  install again. Rollback is not available after migrated state.
- **No answer arrives from a person.** The release stays held, the
  installation keeps serving its active release, and the question stays open in
  the inspector's session until it is answered.
