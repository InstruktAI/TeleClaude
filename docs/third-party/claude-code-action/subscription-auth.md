---
description: Claude Code GitHub Action subscription authentication and its separation from GitHub repository authorization.
---

# Claude Code Action subscription authentication

Anthropic documents subscription authentication through a long-lived token
generated with `claude setup-token`. The Action receives that credential through
`claude_code_oauth_token`. GitHub repository authorization is separate; installing
the GitHub App does not substitute for the model-authentication secret.

The interactive GitHub setup command can register the subscription credential as
the repository secret `CLAUDE_CODE_OAUTH_TOKEN`. Its completed steps remain in
place when setup stops before workflow creation.

Automation supplies a prompt and can pass supported Claude CLI arguments through
`claude_args`. The Action exposes structured output when its invocation uses a
JSON Schema. Event support and actor allow-list handling are version-specific;
this reference contains no live workflow result.

## GitHub credential setup

The Action's automation preparation configures GitHub access and replaces
checkout credentials with its own token or credential helper. A checkout's
non-persistence setting does not remove these subsequent Action effects.

## Limits

Secret presence establishes configuration, not successful authentication or
available subscription quota. Repository content and model output do not acquire
GitHub write authority merely because an Action runs them.

## Sources

- https://code.claude.com/docs/en/github-actions
- https://github.com/anthropics/claude-code-action/blob/main/action.yml
- https://github.com/anthropics/claude-code-action/blob/main/docs/usage.md
- https://github.com/anthropics/claude-code-action/blob/1d6de8cb0c237e7c15e9e1bdf973826ebae490cc/src/github/operations/git-config.ts
