---
description: "The installer provisions SQLite's database sync tool on macOS and Linux
  at one pinned version, in the user tool location a non-interactive SSH session can
  address: idempotent presence handling, integrity-verified fetches, and loud actionable
  failure."
---

# SQLite Sync Tool Provisioning — Spec

## Required reads

- @docs/local/spec/domain/reconciliation.md

## What it is

The behavioral contract for how an installation obtains `sqlite3_rsync`,
SQLite's tool for copying a live database to another computer over SSH while
sending only what differs. Todo state transfer
(`local/projects/teleclaude/spec/feature/workflow/todo-state-transfer`) runs it on both ends of
every transfer, so every computer in the fleet carries it.

The installer places the tool in the user tool location the installer already
provisions for the platform's own commands. A transfer invokes the remote end
through that location rather than through the remote login PATH, which differs
between hosts and does not always include it. Every computer runs the same
pinned release, so both ends of a transfer run identical tool code.

**Business value:** no operator installs the tool by hand on each computer, and
no transfer discovers its absence, or a version mismatch, on the far end at the
moment work is being moved.

## Canonical fields

### Use cases

#### UC-SSP1: A fresh macOS install provisions the tool

```gherkin
Given a macOS host where the sync tool is not installed
When the operator runs the installer
Then the run ends with the tool in the platform's user tool location
And the installer output states that the tool was installed and its version
```

#### UC-SSP2: A fresh Linux install provisions the tool on every supported architecture

```gherkin
Given a Linux host where the sync tool is not installed
And no ready-made build of the tool exists for the host's architecture
When the operator runs the installer
Then the run ends with the tool in the platform's user tool location
And the installer output states that the tool was installed and its version
```

#### UC-SSP3: An already-provisioned host is left untouched

```gherkin
Given a host where the sync tool is already in the platform's user tool location
When the operator re-runs the installer
Then no reinstallation is performed
And the installer output reports that the tool is present
```

#### UC-SSP4: Every host provisions the same deliberately selected release

```gherkin
Given two hosts of different operating systems or architectures
When the operator runs the installer on both
Then both hosts carry the same selected release of the tool, not an implicit latest
```

#### UC-SSP5: A fetched artifact is integrity-verified

```gherkin
Given the installer fetches a release artifact of the tool
When the fetched artifact fails integrity verification
Then nothing from the artifact is placed on the host
And the installer output reports the verification failure
```

#### UC-SSP6: A provisioning failure is loud and actionable

```gherkin
Given a host where the sync tool cannot be provisioned
When the operator runs the installer
Then the installer output names the failed provisioning step with actionable guidance
And the absence of the tool is never silent
```
