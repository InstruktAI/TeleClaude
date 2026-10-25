---
description: Installation of the host's TeleClaude launch units, including withdrawal
  of the retired docs-watch unit from hosts that still carry it.
visibility: internal
---

# Launch Service Installation — Spec

## Required reads

- @docs/local/policy/launch-service-authoring.md

## What it is

A host's installed launch units — launchd agents on macOS, systemd units on Linux —
are machine state. They are not tracked by any repository, so a clone carries none
and a host's set is whatever is deployed on it.

Installation deploys the units TeleClaude declares, content-gated so an unchanged
definition leaves its running service untouched. It runs at installation and nowhere
else: no synchronization path installs, refreshes, or withdraws a launch unit.

The declared units run the platform from the installation's active-release
pointer, never from a release folder or a project checkout
(`local/projects/teleclaude/design/architecture/installation`). Switching the
active release therefore changes no rendered definition, and the content gate
leaves every running unit untouched.

The docs-watch unit is not among the declared units. A host may still carry it
deployed and loaded. Installation withdraws it from any host that does.

Operating a deployed unit — starting, restarting, and reporting its status — belongs
to `local/projects/teleclaude/policy/agent-service-control` and never to installation.

## Canonical fields

- **Withdrawal.** Unloading the docs-watch unit through the host's service manager
  and removing its definition file. A host that does not carry it has nothing to
  withdraw, and installation says so rather than acting.
- **Withdrawal failure.** A withdrawal that begins and cannot complete fails the
  installation: an install that reports success while the docs-watch unit is still
  loaded is a false report.
- **Evidence.** The installer states what it withdrew, and the service manager that
  owns the unit answers for it by name. The owning scope is not the same on both
  platforms: on macOS the unit is a per-user launchd agent, queried in the user's
  GUI domain; on Linux it is a **system** unit under the system manager, deployed
  with elevation, so the answer must come from that same system scope. A user-scope
  query on Linux can answer "not loaded" while the system unit is still running,
  which is the exact failure this evidence exists to catch. Both answers are
  affirmative statements about the named unit; neither is inferred from the absence
  of a report.

### Use cases

#### UC-LSI1: Installation withdraws the retired docs-watch unit

#### UC-LSI2: A host without the unit is left alone

#### UC-LSI3: A withdrawal that cannot complete fails the installation

## Known caveats

- Withdrawal reads the host for the docs-watch unit by name. A unit TeleClaude does
  not declare is outside this contract; on macOS the fleet status check reports such
  a unit, and on Linux no equivalent check exists.
