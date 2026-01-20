---
id: teleclaude/standard/modeling-policy
type: standard
scope: project
description: Data modeling policy for core dataclasses and boundary DTOs.
requires:
  - ../concept/resource-models.md
---

Standard
- Core resource shapes live in teleclaude/core/models.py.
- Boundary validation uses Pydantic; core logic stays dataclass-based.
- API/WS DTOs map 1:1 to core dataclasses with minimal transport metadata.
- Avoid aggregate payloads in API responses.
