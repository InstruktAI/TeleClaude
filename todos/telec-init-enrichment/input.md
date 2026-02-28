# telec init Enrichment — Input

## Context

Today `telec init` does docs sync and auto-rebuild watchers. That's plumbing. The
vision: `telec init` is the most important command in TeleClaude because it's the
moment a raw codebase becomes legible to AI. It bootstraps the intelligence layer
that makes everything else — progressive automation, mesh participation, service
publication — possible.

## The Problem

A fresh project has no documentation structure for AI consumption. The AI has to
discover everything from scratch every session. There's no shared understanding that
persists between sessions. Each new AI session starts cold.

The maturity gap: TeleClaude provides rich SDLC capabilities, but a project without
proper documentation scaffolding can't benefit from them. The AI doesn't know the
architecture, the conventions, the test patterns, the deploy model. It's intelligent
but uninformed.

## What telec init Should Do

### Phase 1: Project Analysis

The AI reads the project. Not a surface scan — a deep analysis:

- Languages, frameworks, patterns
- Entry points, route/handler structure
- Test patterns and coverage model
- Package dependencies and their roles
- Build and deployment model
- Existing documentation (README, inline docs, comments)
- Configuration structure
- Git history patterns (commit style, branching model)

### Phase 2: Documentation Scaffolding

Based on the analysis, scaffold doc snippets that make the codebase self-describing:

- Architecture snippets derived from actual code structure
- Policy stubs inferred from existing conventions (test patterns, commit style)
- Dependency maps from package files
- Entry point documentation from actual route/handler analysis
- A CLAUDE.md / AGENTS.md that reflects THIS project, not a generic template

These aren't boilerplate templates. They're AI-produced analysis turned into durable,
structured documentation. Every future AI session starts with understanding instead
of discovery.

### Phase 3: Hook and Integration Setup

- Set up hooks for the project (pre-commit, sync watchers)
- Register the project with the local TeleClaude instance
- Configure release channel subscription
- Optionally register the node on the mesh (if the user wants to participate)

## Progressive Automation Emerges from Bootstrapping

The progressive automation story is NOT about building automation primitives. It's
an emergent property of how well-bootstrapped the local AI is:

- Fresh project, no docs = L1 (human does everything, AI assists blindly)
- Well-documented project = L2 (AI operates autonomously in known domains)
- Mature project with full SDLC = L3 (AI handles end-to-end, human oversight for
  decisions only)

The progression isn't prescribed. It emerges from context depth. Better docs = more
autonomy. `telec init` is the seed that starts this growth.

## Authorized Author Guidance

The initial documentation pass needs its own procedure — aggressive, thorough,
opinionated about structure but adaptive to what it finds. This is the "authorized
author guidance" for AIs bootstrapping a new project:

- What to look for in each language/framework
- How to structure findings as doc snippets
- How to infer conventions from git history
- How to produce a CLAUDE.md that's useful, not generic
- When to ask the human vs. when to infer

This guidance exists as documentation that the AI consumes during `telec init`. It
doesn't need to be a feature — it's instructions that make the AI better at the
analysis task.

## Cross-Project, Cross-Computer

TeleClaude is the hub in a user's ecosystem. `telec init` applied to every project
means every project gets an intelligence layer. Agents can operate across all projects
on all computers because each project is self-describing. The mesh extends this further:
agents can discover and consume services from other nodes because those nodes also
went through bootstrapping.

## Dependencies

- event-platform (events emitted during init, e.g., `project.initialized`)
- mesh-architecture (optional mesh registration during init)
- event-envelope-schema (format for project lifecycle events)
