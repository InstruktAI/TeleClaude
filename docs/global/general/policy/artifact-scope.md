---
description: 'Determine whether an artifact belongs in global or project scope before creating it.'
visibility: 'public'
---

# Artifact Scope — Policy

## Rules

- Every authored artifact — doc snippet, skill, or command — must have its scope determined before creation.
- Every home — a repository, a person's home, a company's home — has two halves, and an artifact belongs to exactly one:
  - **Global** (`docs/global/`; in a repository also `agents/global/`): the knowledge or tooling is published beyond its home. In a repository that means the domains it publishes — examples: general procedures, cross-project policies, shared CLI tooling. In a person's or company's home it is what that person or company publishes.
  - **Local** (`docs/local/`; in a repository also `agents/local/`): the knowledge or tooling belongs to this home and is never published. Examples: project architecture, repo-specific workflows, local commands, a company's internal procedures.
<!-- planned-change:local-doc-ids-and-person-privacy -->
- The half decides where an artifact is served from, never who may read it. Who reads a snippet, and how deeply, follows the reader's identity and the snippet's `visibility`; a local snippet stays reachable from any location by its qualified id.
<!-- change:local-doc-ids-and-person-privacy -->
- The half decides where an artifact is served from and how a snippet's identity reads: a local snippet's identity begins with `local/`, a published snippet's never does. A local snippet stays reachable from any location by that identity.
- Outside a person's local half, the half never decides who may read a snippet. Who reads it, and how deeply, follows the reader's identity and the snippet's `visibility`.
- A person's local half is readable only by sessions carrying that person's identity and by the system principal. Every other reader, a platform or company administrator included, is refused, and the refusal names the door: the owner's local documentation is private; work in the owner's workspace.
<!-- /planned-change:local-doc-ids-and-person-privacy -->
- Scope must not be inferred or assumed. Apply these criteria:
  1. Does this artifact reference code, architecture, configuration, or knowledge specific to this home? → Local.
  2. Would this artifact be useful in a different home with no changes? → Global.
  3. If neither criterion gives a clear answer, ask the requester before proceeding.
- When redirecting from one authoring procedure to another (e.g., skill gate redirects to doc snippet), the scope question carries over — it must still be answered.

## Rationale

- Agents default to guessing scope when it is not explicit, leading to project-specific knowledge polluting the global namespace or global knowledge trapped in a single repo.
- A single shared policy prevents each authoring procedure from duplicating scope logic.
<!-- planned-change:local-doc-ids-and-person-privacy -->
- Publication and permission are separate questions. Tying confidentiality to the local half would make a snippet's audience depend on where it was filed; `visibility` and the reader's relationship state it once, in the same way for both halves.
<!-- change:local-doc-ids-and-person-privacy -->
- Publication and permission are separate questions. Tying confidentiality to the local half would make a snippet's audience depend on where it was filed; `visibility` and the reader's relationship state it once, in the same way for both halves of every project and company home.
- A person's local half is the one place where filing is the audience. It holds what a person keeps for themselves, and a person is the only tier with exactly one natural owner. Administrative reach exists to govern the platform, and administrator sessions run continuously; letting that reach cover private notes would pull them into unrelated agent work, where only agent discretion would keep them out. Company and project local halves stay under `visibility`, because their help desks serve outsiders the public part of exactly that material.
- Two halves of one home must never share an identity, or a published snippet and a private one at the same relative path could not coexist. The `local/` prefix keeps them apart and lets any reader tell from the identity alone whether a snippet is published.
<!-- /planned-change:local-doc-ids-and-person-privacy -->

## Scope

- Applies to all authoring procedures: doc-snippet-authoring, agent-artifact-authoring, and any future authoring flows.

## Enforcement

- Authoring procedures must include this policy as a Required read.
- An artifact created in the wrong scope is a defect — move it and update references.

## Exceptions

- None.
