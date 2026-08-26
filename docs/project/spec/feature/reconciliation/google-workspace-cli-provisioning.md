---
description: 'The installer provisions the gog Google Workspace CLI as a system dependency on macOS and Linux: idempotent presence handling, integrity-verified fallback fetches, and loud actionable failure.'
delivered_by:
  - installer-gog-dependency
---

# Google Workspace CLI Provisioning — Spec

## Required reads

- @docs/project/spec/domain/reconciliation.md

## What it is

The behavioral contract for how an installation obtains the `gog` Google Workspace CLI — the platform's Google connector for personal-assistant workflows (Gmail triage and drafting, Calendar briefings). The installer treats the connector as a system dependency: every supported host ends an installer run with the binary available, an already-provisioned host is left untouched, any artifact fetched outside a package manager is integrity-verified, and a provisioning failure is reported loudly with actionable guidance.

**Business value:** personal-assistant workflows depend on Google access and run on most installations. Provisioning the connector with the other system dependencies means no operator ever installs it by hand and no agent workflow discovers its absence at the moment it needs Google access. Account and credential wiring stay owned by person onboarding; this contract ends at "binary available".

## Canonical fields

### Use cases

#### UC-GWP-1: A fresh macOS install provisions the connector

```gherkin
Given a macOS host where the Google Workspace CLI is not installed
When the operator runs the installer
Then the run ends with the CLI available on the operator's PATH
And the installer output states that the connector was installed
```

#### UC-GWP-2: A fresh Linux install provisions the connector regardless of Homebrew

```gherkin
Given a Linux host where the Google Workspace CLI is not installed
And the host may or may not have Homebrew available
When the operator runs the installer
Then the run ends with the CLI available on the operator's PATH
And the installer output states that the connector was installed
```

#### UC-GWP-3: An already-provisioned host is left untouched

```gherkin
Given a host where the Google Workspace CLI is already installed
When the operator re-runs the installer
Then no reinstallation is performed
And the installer output reports the installed version
```

#### UC-GWP-4: A provisioning failure is loud and actionable

```gherkin
Given a host where the Google Workspace CLI cannot be provisioned
When the operator runs the installer
Then the installer output names the failed provisioning step with actionable guidance
And the absence of the connector is never silent
```

#### UC-GWP-5: A directly fetched artifact is integrity-verified

```gherkin
Given the installer obtains the connector by fetching a release artifact outside a package manager
When the fetched artifact fails integrity verification
Then the artifact is not placed on the host
And the installer output reports the verification failure
```

#### UC-GWP-6: A direct fetch provisions a deliberately selected version

```gherkin
Given the installer obtains the connector by fetching a release artifact outside a package manager
When the operator runs the installer
Then the version provisioned is the deliberately selected release for that installer state, not an implicit latest
And the installer output states the provisioned version
```
