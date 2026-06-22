---
description: 'Company profile schema declaring the operator organization identity (git host + org) in the global overlay, surfaced into agent sessions like the human profile.'
visibility: 'public'
delivered_by: ['ensure-project-remote']
---

# Company Profile — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

A `CompanyProfile` declares the operating organization's identity in the
platform's global configuration, mirroring how `PersonEntry` declares a human
principal. It is the durable holder of the remote-host + organization the
operator publishes work under. The schema is deliberately narrow: an optional
display `name`, a `git_host` that defaults to `github.com`, and a required,
stripped-non-empty `git_org` (the organization or owner the project repository
lives under, e.g. `InstruktAI`). The profile lives on the global overlay only —
a single per-operator identity, not a per-project or per-person value — and is
rejected at the project and per-person levels by the same disallowed-key
mechanism that keeps `people` global-only.

The company profile is surfaced into every agent session the same way the human
profile is: the hook receiver renders it into the session-start additional
context, so the organization is known to agents from the start without being
asked each time. When no company profile is configured, no company block is
emitted and the agent session simply carries no organization identity.

The profile's `git_host` and `git_org`, combined with a project's
`project_slug`, name the canonical project repository (`<git_org>/<project_slug>`
on `<git_host>`). Project setup consumes the profile to provision a project's
git remote; that consumption is specified in the init-extensions procedure.

## Canonical fields

The authored shape lives on the `CompanyProfile` model in
`teleclaude/config/schema.py`, attached to `GlobalConfig.company_profile`:

- `name` — optional organization display name; defaults to `None`.
- `git_host` — remote host; defaults to `github.com`.
- `git_org` — required organization/owner; whitespace is stripped and the
  stripped value must be non-empty.

### Use cases

#### UC-CFG-COMPANY-1: Minimal company profile accepted

```
Given a global overlay with company_profile { git_org: "InstruktAI" }
When CompanyProfile validation runs
Then git_org is stored as "InstruktAI"
And git_host defaults to "github.com"
And name defaults to None
```

#### UC-CFG-COMPANY-2: Company profile requires a non-empty git_org

```
Given a global overlay with company_profile { name: "Acme" } and no git_org
When CompanyProfile validation runs
Then validation fails because git_org is required and non-empty
```

#### UC-CFG-COMPANY-3: Company profile is global-only

```
Given a project overlay (or a per-person overlay) carrying a company_profile key
When that overlay is validated
Then validation fails with a keys-not-allowed-at-this-level error
And company_profile is accepted only on the global overlay
```

#### UC-CFG-COMPANY-4: Company organization surfaced into agent session context

```
Given a configured global company_profile with git_org "InstruktAI"
When an agent session start composes its additional context
Then the composed context includes a company block naming the organization
```

#### UC-CFG-COMPANY-5: Absent company profile emits no company block

```
Given a global overlay with no company_profile configured
When an agent session start composes its additional context
Then no company block is emitted
And the rest of the session-start context is unaffected
```
