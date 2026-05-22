---
id: 'project/spec/feature/config/agent-env-allow-list'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Global and project-level authorization surfaces for environment variables that may enter agent tmux sessions.'
---

# Agent Env Allow List — Spec

## What it is

`GlobalConfig.env_allow_list` and `ProjectConfig.env_allow_list` are the
user-configurable authorization surfaces for ambient environment variables that
may enter agent tmux sessions. The global allow list lives in
`~/.teleclaude/teleclaude.yml` and is the normal place to authorize variables
needed by global agent skills or CLI integrations. The project allow list lives
in `<project>/teleclaude.yml` and adds repository-specific names without
exposing the whole daemon environment or treating `.env` as an implicit
agent-secret pass-through file.

This feature belongs to the config context because it decides which variable
names are authorized. The agent runtime owns delivery after authorization: it
merges global names first, then project-specific additions, reads the allowed
values from the daemon process environment, and writes them to a private
per-session env file under the session TMPDIR before sourcing that file in the
new shell.

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

### Behavioral contract

```
Given ~/.teleclaude/teleclaude.yml has env_allow_list
And a project teleclaude.yml may also have env_allow_list
When TeleClaude starts a new agent tmux session for that project
Then only names listed in the merged env_allow_list are eligible for pass-through
And global entries are considered before project entries
And each listed value is read from the daemon process environment
And missing variables are skipped
And variables not listed in the merged env_allow_list are not passed through
And the regular project .env is not treated as an implicit allow list
And authorized values are delivered by the agent-runtime private env file, not by tmux command-line -e args
```

```
Given an agent skill needs a secret or account credential
When the project owner trusts the agent with that access
Then the owner adds the variable name to env_allow_list
And ensures the TeleClaude daemon environment contains the value
And starts or restarts the agent session
```

## Allowed values

- `env_allow_list`: list of shell environment variable names.
- Each name must match the agent-runtime validation rule
  `^[A-Za-z_][A-Za-z0-9_]*$` before it can be written to a session env file.

## Known caveats

- Changing `env_allow_list` affects new sessions. Existing agent CLI processes
  do not receive new environment values.
- `.env` is still the standard place for application/runtime secrets, but it is
  not an agent authorization file. A `.env` value reaches an agent only when the
  daemon process has that value and the name is listed in `env_allow_list`.
- The private per-session env file prevents secrets from appearing in tmux
  command-line arguments. It does not decide which variables are allowed; the
  allow list does.
- Wizard editing for the global allow list is target behavior in
  `project/spec/feature/config/setup-wizard`; the implemented v1 behavior
  described here is the config/schema/session-runtime contract.
