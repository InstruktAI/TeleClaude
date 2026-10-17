---
description: 'Global and project-level authorization surfaces for environment variables that may enter agent sessions.'
visibility: 'public'
---

# Agent Env Allow List — Spec

## What it is

The global and project `env_allow_list` fields are the user-configurable
authorization surfaces for ambient environment variables that may enter agent
sessions. The global allow list lives in the global `teleclaude.yml` overlay
and is the normal place to authorize variables needed by global agent skills
or CLI integrations. The project allow list lives in the project's
`teleclaude.yml` and adds repository-specific names without exposing the
whole runtime environment or treating `.env` as an implicit agent-secret
pass-through file.

This feature belongs to the config bounded context because it decides which
variable names are authorized. The agent runtime context owns delivery after
authorization: it merges global names first, then project-specific additions,
reads the allowed values from the runtime process environment, and delivers
them to the new agent session through a private per-session env file rather
than through any command-line argument surface.

## Canonical fields

### Global config shape

```yaml
env_allow_list:
  - GITHUB_TOKEN
  - OPENAI_API_KEY
```

### Project config shape

```yaml
env_allow_list:
  - PROJECT_SPECIFIC_TOKEN
```

### Use cases

#### UC-CFG-ENV-1: A configuration owner authorizes a credential for a trusted agent

```gherkin
Given a configuration owner trusts an agent with a named credential
When the owner adds that variable name to the global or project env_allow_list they control
Then that allow list authorizes the named variable
And no other variable name is authorized by that change
```

### Environment values outside the allow list

The XDG base directories (`XDG_DATA_HOME`, `XDG_CACHE_HOME`) enter a session
through the host-shell capture owned by `local/projects/teleclaude/spec/agent-shell-path`. The
DeepSeek Harness CLI accepts `XDG_*` only from the inherited environment and
refuses any `.env` layer that declares one (`dsh-app-boot` bootstrap-name rule).
Authorizing these names here does not change that delivery.

## Allowed values

- `env_allow_list`: list of shell environment variable names.
- Each name must match the agent-runtime validation rule
  `^[A-Za-z_][A-Za-z0-9_]*$` before it can be written to a session env file.

## Known caveats

- Changing `env_allow_list` affects new sessions. Existing agent CLI processes
  do not receive new environment values.
- `.env` is still the standard place for application/runtime secrets, but it
  is not an agent authorization file. A `.env` value reaches an agent only
  when the runtime process has that value and the name is listed in
  `env_allow_list`.
- The agent runtime's private per-session env file prevents secrets from
  appearing in process-argument surfaces. It does not decide which variables
  are allowed; the allow list does.
- Wizard editing for the global allow list is described in
  `local/projects/teleclaude/spec/feature/config/setup-wizard`; the contract here is the
  config/schema/agent-runtime delivery contract.
