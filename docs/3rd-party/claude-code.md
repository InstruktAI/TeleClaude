# Claude Code Format Specifications

Research sources:

- [Output styles - Claude Code Docs](https://code.claude.com/docs/en/output-styles)
- [Claude Agent Skills: A First Principles Deep Dive](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/)
- [Agent Skills - Claude Code Docs](https://code.claude.com/docs/en/skills)
- [skills/skills/skill-creator/SKILL.md at main](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md)
- [Inside Claude Code Skills: Structure, prompts, invocation](https://mikhail.io/2025/10/claude-code-skills/)
- [Claude Code Hooks Reference](https://docs.anthropic.com/en/docs/claude-code/hooks)

## Overview

Claude Code uses four components that follow the same pattern: a Markdown file with YAML frontmatter at the top. These components are:

1. **Commands** - Slash commands (e.g., `/commit`)
2. **Subagents** - Specialized agents
3. **Skills** - Reusable capabilities
4. **Output Styles** - Custom output formatting

## File Structure

All components follow this structure:

```markdown
---
field1: value1
field2: value2
---

Markdown content with instructions...
```

The frontmatter configures HOW the component runs (permissions, model, metadata), while the markdown content tells Claude WHAT to do.

## Commands Format

### Location

- User commands: `~/.claude/commands/{command-name}.md`
- Project commands: `<project>/.claude/commands/{command-name}.md`

### Required Frontmatter Fields

- `description` (string) - Brief description of the command

### Optional Frontmatter Fields

- `argument-hint` (string) - Gives users a hint about what kind of arguments the command expects
- `model` (string) - Can force a command to run with a specific model
- `allowed-tools` (list or string) - List of tools the command can use

### Example

```yaml
---
description: Create a git commit with proper formatting
argument-hint: "[message]"
allowed-tools: "Bash, Read"
---
# Commit Command

When the user asks to commit changes...
```

## Skills Format (SKILL.md)

### Location

- User skills: `~/.claude/skills/{skill-name}/SKILL.md`
- Project skills: `<project>/.claude/skills/{skill-name}/SKILL.md`

### Required Frontmatter Fields

- `name` (string) - Name of the skill (must match directory name)
- `description` (string) - **Primary triggering mechanism**. Should include both what the Skill does and specific triggers/contexts for when to use it

### Optional Frontmatter Fields

- `allowed-tools` (list or string) - List of tools Claude can use when skill is active (CLI only, not SDK)
- `version` (string) - Metadata field for tracking skill versions (e.g., "1.0.0")

### Important Notes

1. **Description is Critical**: The description field is the primary triggering mechanism. Include all "when to use" information here, not in the body, since the body is only loaded after triggering.

2. **allowed-tools Limitation**: Only works in Claude Code CLI, not in SDK usage.

3. **Format Syntax**: Can use comma-separated string or YAML list:

   ```yaml
   # Comma-separated
   allowed-tools: "Bash, Read, Write"

   # YAML list (cleaner for multiple tools)
   allowed-tools:
     - Bash
     - Read
     - Write
   ```

### Example

```yaml
---
name: reading-files-safely
description: Read files without making changes. Use when user wants to inspect files, analyze code structure, or understand implementation without modification.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
version: "1.0.0"
---
# Reading Files Safely

When invoked, carefully read and analyze files...
```

## Output Styles Format

### Location

- `~/.claude/output-styles/{style-name}.md`

### Required Frontmatter Fields

- `name` (string) - Name of the output style
- `description` (string) - Brief description

### Example

```yaml
---
name: concise
description: Brief, bullet-point responses
---
Respond with:
  - Short bullet points
  - No unnecessary explanation
  - Focus on key facts
```

## Hook Mechanism

Claude Code supports frontmatter-based hooks that can intercept various events in the agent's lifecycle.

### User Request Interception (`UserPromptSubmit`)

The `UserPromptSubmit` hook runs _before_ Claude Code processes a user's prompt. It can be used for validation or context injection.

### Usage in Skills or Commands

Add a `hooks` section to the YAML frontmatter that points to your own hook command.

Example (placeholder command path):

```yaml
---
name: my-skill
description: ...
hooks:
  UserPromptSubmit:
    type: command
    command: "/path/to/your-hook-command --agent claude"
---
```

### Hook Script Interface

- **Input (stdin)**: JSON containing hook payload fields.
- **Output (stdout)**: JSON with `additionalContext` to inject information.

## Hooks Reference (Input/Output Shapes)

Source: Claude Code official hooks reference.

### Configuration (Official)

Hooks are configured in settings files:

- `~/.claude/settings.json` (user)
- `.claude/settings.json` (project)
- `.claude/settings.local.json` (local project)

Structure (per event, with matchers for tool events):

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "ToolPattern",
        "hooks": [
          {
            "type": "command",
            "command": "your-command-here"
          }
        ]
      }
    ]
  }
}
```

Notes:

- `matcher` is only applicable for `PreToolUse` and `PostToolUse`.
- Matchers are case-sensitive tool name patterns.

### Command-Scoped Hooks (Slash Command Frontmatter)

Claude Code slash command files can define hooks directly in frontmatter.
These hooks are scoped to the command's execution and cleaned up after the command finishes.
Supported hook keys in command frontmatter include `PreToolUse`, `PostToolUse`, and `Stop`.

Example (command-scoped hook):

```yaml
---
description: Deploy to staging with validation
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-deploy.sh"
          once: true
---
```

### Hook Input (Base)

All hook inputs include:

- `session_id` — unique session identifier
- `transcript_path` — path to session transcript
- `hook_event_name` — event type identifier

### Hook Input (Event-specific)

**PreToolUse**

- `hook_event_name: "PreToolUse"`
- `tool_name`
- `tool_input`

**PostToolUse**

- `hook_event_name: "PostToolUse"`
- `tool_name`
- `tool_input`
- `tool_response`

**Notification**

- `hook_event_name: "Notification"`
- `message`

**Stop**

- `hook_event_name: "Stop"`
- `stop_hook_active`

**SubagentStop**

- `hook_event_name: "SubagentStop"`
- `stop_hook_active`

**UserPromptSubmit**

- `hook_event_name: "UserPromptSubmit"`
- `prompt`

**PreCompact**

- `hook_event_name: "PreCompact"`
- `trigger`
- `custom_instructions`

### Hook Output (Base)

All hook outputs may include:

- `continue` (boolean) — false to stop processing
- `stopReason` (string)
- `suppressOutput` (boolean)

### Hook Output (Event-specific)

**PreToolUse output**

- `decision: "approve" | "block"`
- `reason` (shown to user when blocking)

**PostToolUse output**

- `decision: "block"`
- `reason`

**Stop output**

- `decision: "block"`
- `reason`

**SubagentStop output**

- `decision: "block"`
- `reason`

**UserPromptSubmit output**

- `decision: "block"`
- `reason`
- `hookSpecificOutput`
  - `hookEventName`
  - `additionalContext`

**Notification / PreCompact output**

- Base fields only

## Recent Updates (2025-2026)

- Added hooks support for skill and slash command frontmatter
- Added support for YAML-style lists in frontmatter `allowed-tools` field for cleaner skill declarations

## Format Validation Rules

### Frontmatter

1. Must be valid YAML
2. Must start with `---` on first line
3. Must end with `---` on its own line
4. Required fields must be present
5. Field values must match expected types

### Content

1. Must be valid Markdown
2. Should contain clear instructions for Claude
3. Should not duplicate information from frontmatter

### File Naming

1. Skills: Directory name must match `name` field in frontmatter
2. Commands: Filename (without .md) becomes the slash command name
3. Output Styles: Filename (without .md) becomes the style name
