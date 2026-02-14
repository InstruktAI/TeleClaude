# Implementation Plan: release-manifests

## Approach

Implement machine-readable specifications within our existing Markdown taxonomy under `docs/project/spec/`. Use embedded YAML code blocks to store the data models. Implement an integration test that extracts these YAML blocks and performs reflection on the CLI, MCP, and Event subsystems.

## Proposed Changes

### 1. Specifications (The Manifests)

- [x] Create `docs/project/spec/telec-cli-surface.md`.
- [x] Create `docs/project/spec/mcp-tool-surface.md`.
- [x] Create `docs/project/spec/event-vocabulary.md` (migrate from `event-types.md`).
- [x] Create `docs/project/spec/teleclaude-config.md`.

### 2. Automated Contract Verification

- [x] Create `tests/integration/test_contracts.py`.
- [x] Implement a YAML extractor helper for Markdown files.
- [x] Implement `test_cli_alignment`: Compare `telec --help` output or internal registry to `telec-cli-surface.md`.
- [x] Implement `test_mcp_alignment`: Compare `mcp_server.get_tools()` to `mcp-tool-surface.md`.
- [x] Implement `test_events_alignment`: Compare `teleclaude.core.events` to `event-vocabulary.md`.
- [x] Implement `test_config_alignment`: Compare `teleclaude.config.schema` to `teleclaude-config.md`.

## Task Sequence

1. [x] Scaffold all four spec files with the current "snapshot" of the system.
2. [x] Develop the `test_contracts.py` suite.
3. [x] Verify that an intentional code change triggers a test failure.
4. [x] Run `telec sync` to update documentation indexes.

## Verification

- `uv run pytest tests/integration/test_contracts.py` must pass.
- `telec sync` must pass without warnings related to these new specs.
