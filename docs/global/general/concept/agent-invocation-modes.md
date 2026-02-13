---
id: 'general/concept/agent-invocation-modes'
type: 'concept'
scope: 'global'
domain: 'software-development'
description: 'Standardized invocation patterns for AI agent CLIs, separating structured extraction from autonomous execution.'
---

# Agent Invocation Modes — Concept

## Definition

TeleClaude utilizes a standardized helper library, `teleclaude/helpers/agent_cli.py`, to manage AI agent CLI interactions. This architecture ensures technical continuity by employing the same command-line interfaces for automated tasks that are used by human operators.

Two distinct invocation modes are supported, defined by their capability sets and security constraints.

## 1. Structured Extraction (Restricted)

**Implementation**: `run_once()`

This mode is designed for deterministic tasks requiring structured output without environmental interaction.

- **Capabilities**: Toolless execution. Network and project configuration access are disabled.
- **Output**: Strictly validated JSON matching a provided schema.
- **Primary Use Cases**:
  - Intent classification.
  - Content summarization.
  - Decision arbitration.
- **Mechanism**: Invokes the agent CLI with flags that suppress interactive features and plugin loading (e.g., `--dangerously-skip-permissions` for Claude, `--yolo` for Gemini).

## 2. Autonomous Work (Elevated)

**Implementation**: `run_job()`

This mode is used for multi-step tasks requiring full environment access and autonomous tool usage.

- **Capabilities**: Full access to shell tools, filesystem operations, and MCP servers.
- **Security**: Permissions are scoped via the `TELECLAUDE_JOB_ROLE` environment variable.
- **Primary Use Cases**:
  - Maintenance routines (e.g., log monitoring).
  - Preparation and readiness gating.
  - Repository-wide analysis.
- **Mechanism**: Spawns an interactive subprocess. The execution environment inherits standard project paths but restricts tool availability based on the assigned role (e.g., `admin`, `maintainer`).

## Technical Continuity

Centralizing agent invocation through these modes ensures that AI-to-AI operations remain auditable and consistent with the project's runtime policy. On macOS, both modes resolve to the standard launcher bundles (e.g., `GeminiLauncher.app`), maintaining unified permission and environment handling across all entry points.

## See Also

- project/design/architecture/jobs-runner
- general/procedure/agent-job-hygiene
