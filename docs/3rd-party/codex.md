# Codex Format Specifications

Research sources:

- [Custom instructions with AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
- [Using PLANS.md for multi-hour problem solving](https://cookbook.openai.com/articles/codex_exec_plans)
- [Custom Prompts](https://developers.openai.com/codex/custom-prompts/)
- [Agent Skills](https://developers.openai.com/codex/skills/)
- [AGENTS.md](https://agents.md)

## Overview

Codex uses standard Markdown with YAML frontmatter for various components:

1. **AGENTS.md** - Project-wide agent configuration
2. **Custom Prompts** - Reusable prompts as slash commands
3. **PLANS.md / ExecPlan** - Complex multi-step task planning
4. **Skills (SKILL.md)** - Reusable capabilities

## AGENTS.md Format

### Purpose

AGENTS.md is a simple, open format for guiding coding agents, serving as a README for agents.

### Characteristics

- Just standard Markdown
- Use any headings you like
- Agent simply parses the text provided
- Codex reads before doing any work
- Can layer global guidance with project-specific overrides

### Location

- Global: `~/.codex/CODEX.md` (formerly AGENTS.md)
- Project: `<project>/AGENTS.md` or `<project>/CODEX.md`

### Format

```markdown
# My Project Guidelines

## Coding Standards

...

## Testing Approach

...
```

## Custom Prompts Format

### Purpose

Custom prompts let you turn Markdown files into reusable prompts that you can invoke as slash commands.

### Location

- User prompts: `~/.codex/prompts/{prompt-name}.md`
- Project prompts: `<project>/.codex/prompts/{prompt-name}.md`

### Required Frontmatter Fields

- `description` (string) - Brief description of the prompt

### Optional Frontmatter Fields

- Other metadata as needed

### Example

```yaml
---
description: Create a git commit with proper formatting
---

When the user asks to commit changes, follow these steps:
1. Run git status
2. Review changes
3. Create commit message...
```

### Invocation

A file at `~/.codex/prompts/commit.md` becomes the command `~/.codex/prompts/commit`

**Note**: Codex cannot run inline commands like Claude's `/commit`. Users must reference the full path `~/.codex/prompts/commit`.

## PLANS.md / ExecPlan Format

### Purpose

For implementing complex tasks that take significant time.

### Format Requirements

1. Must be ONE single fenced code block labeled as `md`
2. Begins and ends with triple backticks
3. Use two newlines after every heading
4. Use # and ## and so on for headings
5. Correct syntax for ordered and unordered lists

### Example

````markdown
```md
# Task: Implement Authentication System

## Step 1: Create User Model

- Define user schema
- Add password hashing
- Create database migration

## Step 2: Create Auth Routes

- POST /login
- POST /register
- GET /profile
```
````

## Skills Format (SKILL.md)

### Purpose

A skill captures a capability expressed through Markdown instructions, and can include scripts, resources, and assets.

### Location

- User skills: `~/.codex/skills/{skill-name}/SKILL.md`
- Project skills: `<project>/.codex/skills/{skill-name}/SKILL.md`

### Required Frontmatter Fields

- `name` (string) - Name of the skill
- `description` (string) - Description to help Codex select the skill

### Example

```yaml
---
name: safe-file-reading
description: Read and analyze files without making modifications
---

# Safe File Reading

When reading files:
1. Use read-only operations
2. Analyze structure
3. Report findings
```

## Format Validation Rules

### Frontmatter

1. Must be valid YAML
2. Must start with `---` on first line
3. Must end with `---` on its own line
4. Required fields must be present

### Content

1. Must be valid Markdown
2. Should contain clear instructions
3. PLANS.md must follow strict formatting rules

### File Naming

1. Skills: Directory name should match `name` field
2. Prompts: Filename (without .md) determines invocation path

## Hook Mechanism

Codex agents support a `UserPromptSubmit` hook that allows executing custom logic before the agent processes the user's input.

### Configuration

Codex hooks are often configured through a plugin system or specific settings files (e.g., `~/.codex/config.toml`).

### Context Injection

To inject context, the hook script can modify the `message` being sent to the model or append context to it.

### Hook Script Interface

- **Input (stdin)**: JSON containing `message` or `input-messages`.
- **Output (stdout)**: JSON with updated `message` or `context`.

```json
{
  "message": "--- CONTEXT ---\n[Snippets here]\n\n--- ORIGINAL PROMPT ---\n[Original user prompt]"
}
```

## Key Differences from Claude Code

1. **No slash command syntax**: Use full path `~/.codex/prompts/name` instead of `/name`
2. **No allowed-tools field**: Codex doesn't support tool restrictions in frontmatter
3. **Prompts directory**: Commands go in `prompts/` not `commands/`
4. **Standard Markdown**: No special formatting requirements beyond standard YAML frontmatter
