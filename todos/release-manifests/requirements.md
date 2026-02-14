# Requirements: release-manifests

## Goal

Define the authoritative public surface of TeleClaude in machine-readable specification files and implement automated contract tests. These "Manifests" serve as the baseline for AI-driven release classification (Patch vs. Minor).

## Scope

- **In scope**:
  - `docs/project/spec/telec-cli-surface.md`: Authoritative list of `telec` subcommands, flags, and arguments.
  - `docs/project/spec/mcp-tool-surface.md`: Authoritative list of Model Context Protocol (MCP) tools, including descriptions and input schemas.
  - `docs/project/spec/event-vocabulary.md`: Authoritative list of internal and external events, including payload field definitions.
  - `docs/project/spec/teleclaude-config.md`: Authoritative list of supported `teleclaude.yml` keys and required environment variables.
  - `tests/integration/test_contracts.py`: Automated tests that assert the live code matches these specifications.
- **Out of scope**:
  - Implementation of the GitHub Actions workflow logic.

## Success Criteria

- [x] All public surface specs follow the project taxonomy (`type: spec`).
- [x] Specs contain embedded YAML/JSON blocks for machine readability.
- [x] `test_contracts.py` fails if any public surface change is detected that is not documented in the specs.
- [x] AI Release Inspectors can deterministically identify classification (e.g., "removed flag" = Minor bump).

## Constraints

- **0.x Semver Policy**: Any removal or rename of a surface element without a documented migration path triggers a "Minor" bump.
- **Single Source of Truth**: The specs in `docs/project/spec/` must be the only source of truth for the manifests.

## Technical Definitions

- **CLI Surface**: The interface humans use via the `telec` tool.
- **MCP Surface**: The interface AI agents use to call internal TeleClaude functions.
- **Event Vocabulary**: The shared language used by adapters and the daemon.
- **TeleClaude Config**: The total configuration surface defined in `teleclaude.yml` and environment variables.
