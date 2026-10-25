---
visibility: internal
description: Terms that name TeleClaude homes and their relations, distinguish the v1 appliance and its maintenance stance from the separately governed replacement authority, and supply the vocabulary its domain anchors and feature inventory use.
---

# Domain Glossary — Spec

## What it is

This glossary fixes the names for the folders TeleClaude configures and acts
on, and prevents v1 maintenance contracts from being confused with the
separately governed replacement program.

## Canonical fields

### Homes

- **Teleclaude home:** a folder whose committed tree holds a `teleclaude.yml`.
  The declaration's kind makes it a **global**, **company**, **person**, or
  **project** home. "Home" alone means a teleclaude home.
- **Global home:** the platform's home at `TELECLAUDE_HOME`.
- **Nested home:** a home inside another home's folder within the same
  repository's committed tree: the company and person homes inside the global
  home. The global home's repository is the only one that holds nested homes,
  because a project home is always the root of its own repository.
- **Owning home:** the nearest home above a path in the same repository's
  committed tree. It owns that path.
- **Home material:** every path a home owns, including folders that hold no
  `teleclaude.yml` of their own, such as a help desk.
- **Foreign root:** a separate repository inside a home's folder. It is never
  part of that home, and its homes belong to its own repository. A project a
  person keeps inside their home's folder is a foreign root of the global home.
- **Tier:** the code's name for the kind of a company or person home.

<!-- planned:platform-installation -->

### Installation

- **Installation:** what the platform runs on a machine — installed releases
  of the repository it follows, under the XDG data directory, apart from every
  project and from the platform home. It is never a home and never a project.
- **Release:** one installed revision: a worktree, at that revision, of the
  repository the installation keeps, with its own environment.
- **Active release:** the release the services and the published `telec` run
  from, addressed through the installation's pointer.
- **Install:** the act that makes a newer revision the active release;
  **rollback** is the act that returns to the previous release after an install
  that ran no migrations
  (`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`).

<!-- /planned:platform-installation -->

### Maintenance and authority

- **v1 appliance:** this Python repository and its running daemon, the operating
  platform until a vNext cut adopts a journey.
- **Maintenance stance:** v1 receives bug fixes and the changes its operators need
  to keep working. It does not acquire new architecture that vNext is designed to
  replace; design authority for the replacement stays in TeleClaudeNext. Domain
  anchors reference this stance rather than restating it, so it is revised in one
  place.
- **Current contract:** a snippet without pending ownership that describes
  observable v1 behavior.
- **Feature inventory:** the current-behavior specs under
  `docs/local/spec/feature/`.
- **Domain anchor:** a stable v1 documentation ID that declares the semantic
  ownership boundary for its feature inventory. The boundary is enforced even
  when several contexts share one process, package tree, database host, or
  runtime service; deployment topology does not weaken ownership.
- **Replacement authority:** the TeleClaudeNext repository named by ADR-0069;
  no vNext architecture in this repository is authoritative.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
