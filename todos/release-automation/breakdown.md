# Release Automation — Breakdown Reasoning

The original `release-automation` todo is too large for a single session and covers multiple distinct architectural layers: contract definition, triple CI lanes, and a consensus mechanism.

## Proposed Split

1. **release-manifests** (Prerequisite)
   - Define the JSON/YAML manifests for CLI, MCP, Events, and API.
   - Implement contract tests that verify the current codebase matches these manifests.

2. **release-workflow-foundation**
   - Ensure lint and tests are stable and deterministic in CI.
   - Create the initial release workflow that triggers on main pushes.

3. **release-lane-claude**
   - Implement the first AI lane using `anthropics/claude-code-action`.
   - Develop the "Inspector" prompt for Claude.

4. **release-lane-codex**
   - Implement the second AI lane using `openai/codex-action`.
   - Align the Codex lane output with the shared report schema.

5. **release-lane-gemini**
   - Implement the third AI lane using Gemini.
   - Develop the "Inspector" prompt for Gemini.

6. **release-arbiter**
   - Implement the final consensus step.
   - Authorized tagging and GitHub Release creation based on Arbiter JSON output (consuming Claude, Codex, and Gemini reports).
