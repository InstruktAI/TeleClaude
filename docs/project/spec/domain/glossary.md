---
visibility: internal
description: Terms that distinguish the frozen v1 appliance, its current feature inventory, and the separate replacement authority.
---

# Domain Glossary — Spec

## What it is

This glossary prevents v1 maintenance contracts from being confused with the
separately governed replacement program.

## Canonical fields

- **v1 appliance:** this Python repository and its running daemon, kept stable
  only for approved P0 maintenance while replacement proceeds.
- **Current contract:** a snippet without pending ownership that describes
  observable v1 behavior.
- **Feature inventory:** the current-behavior specs under
  `docs/project/spec/feature/`.
- **Domain anchor:** a stable v1 documentation ID used to classify and prime
  feature inventory without asserting an enforced service boundary.
- **Replacement authority:** the TeleClaudeNext repository named by ADR-0069;
  no vNext architecture in this repository is authoritative.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
