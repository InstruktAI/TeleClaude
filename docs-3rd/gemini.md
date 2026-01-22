# Gemini CLI Format Specifications

Research sources:

- [Gemini CLI: Custom slash commands](https://cloud.google.com/blog/topics/developers-practitioners/gemini-cli-custom-slash-commands)
- [Gemini CLI Tutorial Series — Part 7: Custom slash commands](https://medium.com/google-cloud/gemini-cli-tutorial-series-part-7-custom-slash-commands-64c06195294b)
- [Hands-on with Gemini CLI](https://codelabs.developers.google.com/gemini-cli-hands-on)
- [Gemini CLI | Gemini Code Assist](https://developers.google.com/gemini-code-assist/docs/gemini-cli)
- [Gemini CLI Hooks Reference](https://github.com/google-gemini/gemini-cli/docs/hooks/reference.md)

## Overview

Gemini CLI uses TOML format for custom slash commands. The format is structured, human-readable, and designed for defining reusable prompt templates.

## Custom Commands Format

### File Format

Custom commands are defined in simple text files using the `.toml` format.

### Location and Naming

**User-scoped commands** (available across all projects):

- `~/.gemini/commands/{command-name}.toml` → `/command-name`

**Project-scoped commands** (available only in that project):

- `<project>/.gemini/commands/{command-name}.toml` → `/command-name`

**Namespaced commands**:

- `~/.gemini/commands/git/commit.toml` → `/git:commit`
- `<project>/.gemini/commands/test/unit.toml` → `/test:unit`

### Required Fields

- `prompt` (string) - The prompt sent to the Gemini model when the command is executed
  - Can be single-line or multi-line string

### Optional Fields

- `description` (string) - Brief, one-line description displayed in `/help` menu
  - If omitted, a generic description will be generated from the filename

### Basic Example

```toml
description = "Create a git commit with proper formatting"
prompt = '''
When the user asks to commit changes:
1. Run git status
2. Review changes
3. Create commit message following commitizen format
'''
```

### Multi-line Prompt Example

```toml
description = "Analyze code for security vulnerabilities"
prompt = '''
Perform a security analysis of the provided code:

1. Check for common vulnerabilities (OWASP Top 10)
2. Identify input validation issues
3. Look for hardcoded secrets
4. Review authentication/authorization logic
5. Report findings with severity levels
'''
```

## Advanced Features

### Argument Substitution

Commands support argument substitution using `{{args}}`:

```toml
description = "Search the codebase for a pattern"
prompt = '''
Search for the following pattern: {{args}}

1. Use appropriate search tools
2. Show matches with context
3. Group by file
'''
```

### Shell Command Execution

Commands can include shell execution directives:

```toml
description = "Run tests and report coverage"
prompt = '''
Execute the test suite:

Run: `pytest --cov=. --cov-report=term`

Then analyze the coverage report and highlight:
- Files with < 80% coverage
- Uncovered critical paths
- Suggested test additions
'''
```

### File Content Injection

Commands can reference file content for context:

```toml
description = "Review pull request"
prompt = '''
Review the changes in this pull request.

Consider:
- Code quality and style
- Test coverage
- Security implications
- Performance impact
'''
```

## Format Validation Rules

### TOML Syntax

1. Must be valid TOML format
2. String values use double quotes or triple single quotes (for multi-line)
3. Required fields must be present

### Field Requirements

1. `prompt` field is REQUIRED
2. `description` field is OPTIONAL but recommended
3. Field names are lowercase

### File Naming

1. Filename (without .toml) determines command name
2. Subdirectories create namespaces (e.g., `git/commit.toml` → `/git:commit`)
3. Use lowercase, hyphen-separated names

## Hook Mechanism (Experimental)

Gemini CLI supports an experimental hooks system that allows intercepting and customizing behavior at predefined lifecycle events. Hooks are programs that receive JSON via `stdin` and can return JSON on `stdout`.

### Lifecycle Events

- `SessionStart`
- `Notification`
- `SessionEnd`
- `BeforeAgent`
- `BeforeModel`
- `AfterModel`
- `BeforeToolSelection`
- `BeforeTool`
- `AfterTool`
- `PreCompress`

### Context Injection Example

To inject context before the agent processes a request, use the `BeforeAgent` hook with your own command.

**Settings Configuration (`~/.gemini/settings.json`)**:

```json
{
  "hooks": {
    "enabled": true,
    "BeforeAgent": [
      {
        "matcher": "*",
        "hooks": [
          {
            "name": "context-hook",
            "type": "command",
            "command": "/path/to/your-hook-command --agent gemini",
            "description": "Inject matching documentation snippets"
          }
        ]
      }
    ]
  }
}
```

### Hook Script Interface

- **Input (stdin)**: JSON containing current prompt and session metadata.
- **Output (stdout)**: JSON with `hookSpecificOutput.additionalContext` to inject text.

```json
{
  "hookSpecificOutput": {
    "additionalContext": "The content to be injected into the LLM context window."
  }
}
```

## Hooks Reference (Input/Output Shapes)

Source: Gemini CLI official hooks reference.

### Hook Input (Base)

All hook inputs include:

- `session_id`
- `transcript_path`
- `cwd`
- `hook_event_name`
- `timestamp`

### Hook Input (Event-specific)

**Tool Events (`BeforeTool`, `AfterTool`)**

- `tool_name`
- `tool_input`
- `tool_response` (AfterTool only)

**Agent Events (`BeforeAgent`, `AfterAgent`)**

- `prompt`
- `prompt_response` (AfterAgent only)
- `stop_hook_active` (AfterAgent only)

**Model Events (`BeforeModel`, `AfterModel`, `BeforeToolSelection`)**

- `llm_request`
- `llm_response` (AfterModel only)

**Session/Notification Events**

- `source` (SessionStart only)
- `reason` (SessionEnd only)
- `trigger` (PreCompress only)
- `notification_type`, `message`, `details` (Notification only)

### Hook Output (Common)

If the hook exits with `0`, stdout is parsed as JSON.

Common fields:

- `decision` — `allow | deny | block | ask | approve`
- `reason` — shown to the agent when blocking/denying
- `systemMessage` — shown to the user in CLI
- `continue` — `false` terminates the agent loop for this turn
- `stopReason`
- `suppressOutput`
- `hookSpecificOutput` — event-specific data

### Context Injection (BeforeAgent)

Hook can inject additional context using:

```json
{
  "decision": "allow|deny",
  "hookSpecificOutput": {
    "hookEventName": "BeforeAgent",
    "additionalContext": "Recent project decisions: ..."
  }
}
```

### Exit Codes (Fallback Behavior)

- Exit `0` → allow (stdout processed)
- Exit `2` → deny (stderr shown to agent)
- Other → warning (logged, continues)

## Key Differences from Claude Code and Codex

1. **TOML format**: Uses TOML instead of Markdown with YAML frontmatter
2. **Simpler structure**: Only `description` and `prompt` fields, no complex metadata
3. **Argument syntax**: Uses `{{args}}` instead of `$ARGUMENTS`
4. **Namespacing**: Supports command namespacing through subdirectories
5. **Slash commands**: Supports true slash command syntax like Claude (`/name`)

## Example Command Files

### Simple Command

**File**: `~/.gemini/commands/commit.toml`

```toml
description = "Create a commit"
prompt = "Help the user create a well-formatted git commit message."
```

**Usage**: `/commit`

### Command with Arguments

**File**: `~/.gemini/commands/search.toml`

```toml
description = "Search codebase"
prompt = "Search for: {{args}}"
```

**Usage**: `/search AuthService`
