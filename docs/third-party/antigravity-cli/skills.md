---
description: Antigravity CLI (agy) Skills Spec
---

# Antigravity CLI (agy) Skills Spec

## Overview

The Antigravity CLI (`agy`) natively supports **Agent Skills**, extending the capabilities of the agent for complex or domain-specific tasks. Skills are structured directories containing a main markdown instruction file, supporting scripts, resources, and reference materials.

## Skill Folder Structure

Each skill is encapsulated inside its own named directory and must follow a standardized schema:

```
[skill-name]/
├── SKILL.md         # (Required) Main instructions file with YAML frontmatter
├── scripts/         # (Optional) Executable scripts or utility binaries
├── examples/        # (Optional) Reference implementations and code samples
└── resources/       # (Optional) Additional static assets, files, or templates
```

### `SKILL.md` Format

The `SKILL.md` file defines the skill's metadata using YAML frontmatter and provides a detailed instruction set for the agent:

```markdown
---
name: Database Optimizer
description: Tools and instructions for identifying and resolving database slow queries and schema bottlenecks.
---

# Database Optimizer Skill

## Instructions

1. Run the query analysis script under `scripts/analyze.sh` against the database container.
2. Read the results from `resources/query_log.json`.
3. Propose optimizations or index creation rules.
```

## Skill Discovery Locations

`agy` scans for skills under the following tiered directories on startup:

| Scope               | Antigravity CLI Location (`agy`)    | Description                                                  |
| :------------------ | :---------------------------------- | :----------------------------------------------------------- |
| **User Global**     | `~/.gemini/antigravity-cli/skills/` | Available across all local terminal sessions and workspaces. |
| **Workspace Local** | `.agents/skills/`                   | Restricted to the active project workspace directory.        |

## Runtime Execution

When a skill is loaded by the agent:

- **Sandbox Mounts**: If `agy` is running in `--sandbox` mode, the directories representing active workspace-local and global skills are automatically mounted into the restricted container to allow script execution.
- **Tool Access**: The agent is allowed to query and run files inside the skill's `scripts/` directory, adhering to the standard sandbox execution limits unless explicitly overridden by policy rules.

## Sources

- https://antigravity.google/docs/skills
- https://dev.to/google/antigravity-cli-2-0
- https://antigravity.google/docs/gcli-migration
