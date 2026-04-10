---
id: general/spec/project-third-party-index
type: spec
scope: project
description: Index of curated third-party research notes stored under docs/third-party for this repository.
---

# Project Third-Party Index — Spec

## What it is

This file is a soft-reference index of the repository's curated third-party research notes under `docs/third-party/`.

## Canonical fields

- Entries in this index point to repository-local third-party research notes.
- This index uses plain path references, not inline `@` required-read references.
- Authoritative vendor links belong in each leaf research note's `## Sources` section.

## Known caveats

- `teleclaude/docs_index.py` still generates `docs/third-party/index.md` as raw `@` references. This checked-in file preserves the validator-compatible shape expected by the current snippet rules.
- This index is descriptive only; `docs/third-party/index.yaml` remains the machine-oriented catalog.

## See also

- docs/third-party/a2a-protocol/agent-card.md
- docs/third-party/a2a-protocol/api-methods.md
- docs/third-party/a2a-protocol/mcp-integration.md
- docs/third-party/a2a-protocol/overview.md
- docs/third-party/a2a-protocol/python-sdk.md
- docs/third-party/a2a-protocol/task-lifecycle.md
- docs/third-party/a2ui/overview.md
- docs/third-party/ag-ui/overview.md
- docs/third-party/art-of-hosting/chaordic-design.md
- docs/third-party/art-of-hosting/harvesting.md
- docs/third-party/art-of-hosting/methods.md
- docs/third-party/art-of-hosting/overview.md
- docs/third-party/claude-code/commands.md
- docs/third-party/claude-code/hooks.md
- docs/third-party/claude-code/permissions.md
- docs/third-party/claude-code/skills.md
- docs/third-party/claude-code/sub-agents.md
- docs/third-party/codex-cli/commands.md
- docs/third-party/codex-cli/configuration.md
- docs/third-party/codex-cli/hooks.md
- docs/third-party/codex-cli/permissions.md
- docs/third-party/codex-cli/skills.md
- docs/third-party/codex-cli/sub-agents.md
- docs/third-party/discord/bot-api.md
- docs/third-party/discord/gateway-delivery-guarantees.md
- docs/third-party/discord/message-formatting.md
- docs/third-party/gemini-cli/commands.md
- docs/third-party/gemini-cli/hooks.md
- docs/third-party/gemini-cli/permissions.md
- docs/third-party/gemini-cli/skills.md
- docs/third-party/gemini-cli/sub-agents.md
- docs/third-party/image-generation/gemini-nano-banana.md
- docs/third-party/image-generation/landscape.md
- docs/third-party/json-schema-to-typescript/overview.md
- docs/third-party/tmux/session-output-observation.md
- docs/third-party/whatsapp/cloud-api.md
- docs/third-party/whatsapp/media-api.md
- docs/third-party/whatsapp/messages-api.md
- docs/third-party/whatsapp/rate-limits-errors.md
- docs/third-party/whatsapp/webhooks.md
