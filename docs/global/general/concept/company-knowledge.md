---
description: 'Company knowledge layer — organizational policies, procedures, and domain context available to all projects belonging to a company.'
visibility: 'public'
---

# Company Knowledge — Concept

## What

Company knowledge is the organizational layer between global platform docs and
project-specific docs. It captures the policies, procedures, principles, domain
language, and structural context of a company (or organization, nonprofit, solo
practice — any entity that owns projects).

The knowledge lives under `~/.teleclaude/companies/{slug}/` and is stored as
taxonomy-conformant doc snippets with `company/` prefix IDs. When an agent session
starts in a project linked to a company (`company: <slug>` in `teleclaude.yml`),
the company's doc snippets are loaded alongside global and project docs.

### Scope hierarchy

```
global (platform docs) → company (organizational docs) → project (repo docs)
```

Global docs are always available. Company docs are available to projects that
declare membership. Project docs are available only within their repository.
The context selector merges all three tiers, with project docs taking precedence
over company docs, which take precedence over global docs when IDs collide.

### What it contains

Company knowledge maps to the same taxonomy as all other doc snippets:

| Taxonomy    | Company examples                                                    |
| ----------- | ------------------------------------------------------------------- |
| `principle` | Engineering principles, cultural values, design philosophy          |
| `concept`   | Domain model, org structure, team topology, product lines           |
| `policy`    | HR policies, security standards, coding standards, compliance rules |
| `procedure` | Onboarding flows, deployment procedures, incident response          |
| `design`    | System architecture, infrastructure topology                        |
| `spec`      | API contracts, data schemas, service inventory                      |

### Company applications

Alongside the knowledge snippets, the company home holds `apps/` — company-coupled
software projects at `~/.teleclaude/companies/{slug}/apps/<app>/`, each a first-class
project with its own git repository and `AGENTS.md`. Awareness is the folder and its
member names: an agent lists `apps/` to learn what software a company owns, and reads a
given app's own docs only when it operates that app — the apps are never bulk-loaded into
session context. Agents build software bound to a company here, so its location is always
known. An outward integration or adapter is one kind of company app; it runs outside any
system it bridges and reflects state one way rather than syncing.

### What it is not

- Not project-specific code conventions — those belong in `project/` scope.
- Not global platform knowledge — that belongs in `global/` scope.
- Not third-party library docs — those belong in `third-party/`.
- Not ephemeral task context — that belongs in session memory or todos.
- Not company-coupled application code — that lives in the company `apps/` home as
  first-class projects, discovered by listing the folder, never loaded as knowledge.

### Multi-company awareness

A single TeleClaude installation can host multiple companies. Each company has
its own `~/.teleclaude/companies/{slug}/` directory with isolated docs. Projects
link to exactly one company via their `teleclaude.yml` config. Company knowledge
never leaks across company boundaries — the context selector filters by the
project's declared company.

## Why

AI agents starting a session in a company's project currently have no
organizational context. They know the platform policies (global) and the repo
structure (project), but nothing about the company's standards, domain language,
or operational procedures. This gap causes:

- Agents proposing solutions that violate company policies they don't know about.
- Repeated explanation of company-specific terminology and conventions.
- Inconsistent behavior across projects that should share organizational standards.
- No durable place to store organizational knowledge that outlives individual sessions.

The company knowledge layer fills this gap by giving agents the organizational
context at session start, the same way global docs give them platform context.
