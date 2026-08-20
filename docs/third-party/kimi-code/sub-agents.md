---
description: Kimi Code main-agent selection, custom-agent discovery, and sub-agent persistence for runtime 0.37.2.
---

# Kimi Code Sub-Agents

## Agent selection

The installed CLI accepts `--agent <name>` and `--agent-file <path>` for a new
session. Both are rejected with `--session` or `--continue`; the selected agent
is bound when the session begins and is restored on resume.

The vendor documents custom agents as Markdown files with YAML frontmatter and
system-prompt bodies. Discovery precedence is explicit `--agent-file`, project,
extra, user, plugin, then built-in. Project roots are `.kimi-code/agents/` and
`.agents/agents/`; user roots are `$KIMI_CODE_HOME/agents/` and
`~/.agents/agents/`; `extra_agent_dirs` adds further roots.

## Delegation and persistence

Kimi Code has built-in sub-agents and can delegate custom agents as sub-agents.
The installed session layout persists each agent under the parent session's
`agents/<agent-name>/wire.jsonl`; those sibling agent directories are not
independent top-level sessions.

Custom agent frontmatter can restrict available tools and the sub-agent types
that an agent may delegate to. Project-scoped agent files can replace built-in
system prompts when their frontmatter allows it, so vendor guidance treats them
as prompt configuration that should be reviewed in unfamiliar repositories.

## Gaps

- No custom agent or sub-agent was launched in the installed runtime.
- Built-in agent names, tool inventories, and delegation concurrency were not
  independently verified for 0.37.2.

## Sources

- https://moonshotai.github.io/kimi-code/en/customization/agents
- https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html
