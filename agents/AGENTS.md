# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

**Project root:** `~/.agents`

This repository manages agent command definitions and tooling that get distributed to multiple AI agents (Claude Code, Codex, Gemini). Commands are written once in a master format and transpiled to agent-specific formats with appropriate command prefixes and syntax.

## Build & Distribution System

### Building Distributions

```bash
# Build only (generates dist/ directory with agent-specific files)
./bin/distribute.py

# Build and deploy (generates dist/ + copies to ~/.claude, ~/.codex, ~/.gemini)
./bin/distribute.py --deploy
```

**Important:** The script uses `uv run` via shebang to automatically manage dependencies. No manual venv management needed.

### Distribution Architecture

- **Master files:**
  - `AGENTS.master.md` - Core agent behavior (transpiled to CLAUDE.md, CODEX.md, GEMINI.md)
  - `commands/*.md` - Command definitions (transpiled to each agent's command format)
  - `skills/*/SKILL.md` - Skill definitions (transpiled to each agent's skill format)
  - `PREFIX.{agent}.md` - Agent-specific preamble content (optional)

- **Transpilation:**
  - Claude: Preserves frontmatter as-is, uses `/` prefix
  - Codex: Transforms to Codex format with `subject=<arg>` syntax, uses `~/.codex/prompts/` prefix, outputs to `prompts/` directory
  - Gemini: Transforms to TOML format with `{{args}}` substitution, uses `/` prefix

- **Placeholder substitution:**
  - `{AGENT_PREFIX}` → agent-specific command prefix
    - Claude: `/` (e.g., `/next-work`)
    - Codex: `~/.codex/prompts/` (e.g., `~/.codex/prompts/next-work`)
    - Gemini: `/` (e.g., `/next-work`)

- **Deploy targets:**
  - `dist/claude/*` → `~/.claude/`
  - `dist/codex/*` → `~/.codex/`
  - `dist/gemini/*` → `~/.gemini/`

Skills are distributed to:

- Claude: `dist/claude/skills` → `~/.claude/skills`
- Codex: `dist/codex/skills` → `~/.codex/skills`
- Gemini: `dist/gemini/skills` → `~/.gemini/skills`

## Code Quality & Testing

### Linting & Type Checking

```bash
# Run linting and type checking with uv
uv run pylint bin/**/*.py
uv run mypy bin
```

**Critical linting rules:**

- `import-outside-toplevel` (C0415) is ENABLED and will fail the build
- ALL imports MUST be at the top of the file
- Type annotations required for all functions (no `Any` allowed except with justification)

### Guardrails Exclusions

Guardrails checks can be suppressed per-function using a docstring tag on the function itself.
Use this only when the exception is intentional and justified.

### Testing

```bash
# Run all tests with parallel execution
uv run pytest -n auto -v

# Run specific test file
uv run pytest -n auto tests/unit/test_distribute.py -v

# Run single test method
uv run pytest -n auto tests/unit/test_distribute.py::TestClass::test_method -v
```

**Note:** Always use `-n auto` for parallel execution. Use timeout=3000ms (3s) for unit tests, timeout=15000ms (15s) for integration tests when calling via Bash tool.

## Architect-Builder Workflow

This repository implements a two-role AI paradigm:

### Architect Role

Strategic planning, requirements definition, architecture documentation.

**Commands:**

- `/prime-architect` - Load strategic context
- `/next-roadmap` - Groom and prioritize roadmap
- `/next-work [slug]` - Find and implement next item (master orchestrator)
- `/sync-todos` - Sync todos with architecture and code

### Builder Role

Tactical implementation, bug fixes, test writing.

**Commands:**

- `/prime-builder` - Load implementation context
- `/next-build [slug]` - Execute implementation plan

### Fixer Role

Tactical execution: investigate, isolate, and resolve bugs.

**Commands:**

- `/prime-fixer` - Load debugging and fixing context
- `/next-bugs` - Execute bug fixing plan

### State Tracking

Work progress is tracked through file existence and content in `todos/` directory:

- `todos/bugs.md` - Bug tracking (checked items = resolved)
- `todos/roadmap.md` - Feature roadmap with `[ ]`, `[>]`, `[x]` markers
- `todos/{slug}/requirements.md` - Feature requirements
- `todos/{slug}/implementation-plan.md` - Implementation plan with task groups
- `todos/{slug}/review-findings.md` - Code review results

## Key Architecture Patterns

### Command Structure

All commands use frontmatter metadata:

```markdown
---
description: Human-readable command description
argument-hint: "[optional-arg]"
---

Command implementation using {AGENT_PREFIX} placeholder...
```

### Frontmatter Transform Functions

- `transform_to_codex()` - Converts to Codex format with `subject=<arg>` syntax
- `transform_to_gemini()` - Converts to TOML with `{{args}}` substitution
- Default (Claude) - Preserves frontmatter structure

### Agent-Specific Prefixes

The codebase handles different command invocation patterns:

- **Claude:** Direct slash commands (`/next-work`)
- **Codex:** Cannot run inline commands, must read prompt file first (`~/.codex/prompts/next-work.md`)
- **Gemini:** Slash commands with `{{args}}` substitution

## Documentation Structure

- `docs/snippets/` - Local snippets for this repo only
- `docs/3rd-party/` - Research material (not used for snippets)
- `README.md` - Project overview and build instructions
- `AGENTS.master.md` - Master agent behavior template

## Global Snippets (Meta)

This repo owns the **global** snippet library under `docs/global-snippets/`.
Do not document or mirror its contents here. Treat it as a separate distribution artifact.

## Snippet Tooling

- `scripts/build_snippet_index.py` - Build `docs/index.yaml` from `docs/snippets/`
- `scripts/sync_snippets.py` - Validate `docs/index.yaml` against snippets
- Snippets use YAML frontmatter with `id`, `description`, `type`, `scope`, and optional `requires`.

## Project Dependencies

Python environment managed via `uv`:

- `pyproject.toml` - Project metadata, dependencies, and tool configuration
  - Runtime dependencies: python-frontmatter, pyyaml
  - Dev dependencies: pytest, pytest-xdist, mypy, pylint, black, isort
- `uv` automatically manages virtual environment and dependencies
- No manual venv management needed

## Common Development Tasks

1. **Adding a new command:**
   - Create `commands/new-command.md` with frontmatter
   - Use `{AGENT_PREFIX}` placeholder for command references
   - Run `./bin/distribute.py` to test transpilation
   - Run `./bin/distribute.py --deploy` to deploy

2. **Modifying AGENTS behavior:**
   - Edit `AGENTS.master.md` for shared behavior
   - Edit `PREFIX.{agent}.md` for agent-specific preamble
   - Run `./bin/distribute.py --deploy`

## Git Workflow

- All imports must be at top-level (C0415 enabled)
- Commit format: `type(scope): subject` (commitizen style)
- Attribution footer required (see coding-directives.md)
- Never commit before testing `bin/distribute.py`.
