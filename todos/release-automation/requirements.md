# Requirements: Release Automation

## Goal

Implement a fully automated, evidence-driven release pipeline where a dedicated AI inspector analyzes diffs, verifies contracts, and decides on semantic versioning (patch/minor) without human intervention for non-breaking changes.

## Scope

1.  **AI Release Inspector**: Single-pass analysis of git diffs vs last tag.
2.  **Dual-Lane Verification**: Parallel execution of Claude Code and Codex CLI agents to cross-verify release decisions.
3.  **Consensus Arbiter**: A third step that synthesizes lane reports into a final JSON decision.
4.  **GitHub Integration**: Automated tagging, release creation, and changelog generation based on Arbiter output.
5.  **Contract Manifests**: Explicit definitions of public surface (CLI, MCP, Config) to guide the AI's "breaking change" detection.

## Functional Requirements

### FR1: Release Inspector Logic

- **Input**: Git diff between `HEAD` and `latest_tag`.
- **Context**: Access to `docs/global/**` (contracts) and `teleclaude/**` (source).
- **Decision**:
  - `PATCH`: Logic fix, internal refactor, doc update, non-breaking add.
  - `MINOR`: New feature (backward compatible), new public API surface.
  - `SKIP`: No release needed (CI-only changes, noise).
  - `BLOCK`: Breaking change detected (requires manual MAJOR decision).

### FR2: Dual-Lane Pipeline

- **Lane A (Claude)**: Runs `anthropics/claude-code-action` with inspector prompt. Output: `claude_report.json`.
- **Lane B (Codex)**: Runs `openai/codex-action` with inspector prompt. Output: `codex_report.json`.
- **Isolation**: Both lanes run in parallel on the same commit.

### FR3: Consensus Arbiter

- **Input**: `claude_report.json`, `codex_report.json`.
- **Logic**:
  - If both agree -> Proceed.
  - If mismatch -> Pick conservative option (e.g., Block over Release, Minor over Patch).
- **Output**: `release_decision.json` (authoritative).

### FR4: GitHub Action Workflow

- **Trigger**: Push to `main`.
- **Pre-check**: Lint/Test must pass.
- **Execution**: Run Lanes -> Run Arbiter -> (If Release) -> Tag & Publish.

## Non-functional Requirements

- **Idempotency**: Re-running on the same commit must produce the same result (or skip if already tagged).
- **Auditability**: All agent reasoning must be captured in the Release Description.
- **Cost**: Run on `main` push only, not every PR.

## Acceptance Criteria

1.  Pushing a fix to `main` triggers the workflow.
2.  Agents correctly identify it as `PATCH`.
3.  A new `vX.Y.Z+1` tag is pushed.
4.  A GitHub Release is created with AI-generated notes.
5.  Pushing a breaking change results in a `BLOCK` decision (no tag).
