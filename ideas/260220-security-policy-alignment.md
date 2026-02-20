# Security Policy Alignment — Idea

## Summary

Memory ID 39: "CLI agent auth: OAuth only, API keys stripped" — This is a strong decision that clarifies authentication boundaries, but it lives only in memory, not in documented policy.

## Current State

- **Decision made**: OAuth for CLI agents, API keys reserved for SDK operations
- **Implementation complete**: `agent_cli.py` strips API keys from subprocess env
- **Not documented**: No formal policy doc explains the security model

## Pattern

This is part of a broader **security decision pattern** where architectural choices are made to enforce boundaries:

- **Least privilege**: API keys go only to SDK operations that need speed
- **Process isolation**: CLI subprocesses can't access API keys
- **Clear intent**: The boundary prevents accidental direct API charges

## Actionable Insights

1. **Formalize the security model**: Document the authentication architecture in a spec that explains:
   - Why CLI agents use OAuth
   - Why API keys are dangerous in subprocess env
   - How the boundary is enforced and verified

2. **Audit coverage**: Create a security audit procedure that checks:
   - `agent_cli.py` still strips keys correctly
   - No new code leaks API keys to subprocesses
   - Environment variable policy is documented

3. **Onboarding clarity**: New agents need to understand the security model from docs, not from memory.

## Next Steps

- Create `docs/project/spec/agent-authentication-model.md`
- Add security audit to pre-commit checks
- Add environment variable policy to `AGENTS.md`

## Related Memories

- ID 39: CLI agent auth: OAuth only, API keys stripped
- ID 36: AI stash policy and communication preference
