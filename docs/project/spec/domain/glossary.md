---
visibility: internal
description: Terms that distinguish the v1 appliance and its maintenance stance from the separately governed replacement authority, plus the vocabulary its domain anchors and feature inventory use.
---

# Domain Glossary — Spec

## What it is

This glossary prevents v1 maintenance contracts from being confused with the
separately governed replacement program.

## Canonical fields

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
  `docs/project/spec/feature/`.
- **Domain anchor:** a stable v1 documentation ID that declares the semantic
  ownership boundary for its feature inventory. The boundary is enforced even
  when several contexts share one process, package tree, database host, or
  runtime service; deployment topology does not weaken ownership.
- **Replacement authority:** the TeleClaudeNext repository named by ADR-0069;
  no vNext architecture in this repository is authoritative.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
