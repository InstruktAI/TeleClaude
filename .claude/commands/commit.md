---
description: Create a git commit with commitizen-style message
---

You are now in **commit mode**. Follow these steps to create a well-formatted git commit:

## Step 1: Analyze Current Changes

Run these git commands in parallel:
- `git status` - See all staged and unstaged changes
- `git diff --cached` - See staged changes in detail
- `git diff` - See unstaged changes
- `git log --oneline -10` - Review recent commit style

## Step 2: Draft Commitizen Message

Analyze the changes and create a commitizen-style commit message:

**Format:**
```
<type>(<scope>): <subject>

<optional body>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code restructuring without behavior change
- `style`: Formatting, whitespace (no code change)
- `docs`: Documentation only
- `test`: Adding/updating tests
- `chore`: Build process, dependencies, tooling
- `perf`: Performance improvement

**Scope:** Optional component/module affected (e.g., `monitor`, `proxy`, `logging`)

**Subject:**
- Imperative mood ("add" not "added")
- No capitalization
- No period at end
- Max 72 characters

**Body:** Optional detailed explanation (wrap at 72 chars)

## Step 3: Format, Stage and Commit

1. Run bin/format.sh to auto-format code (if present in project)
2. Stage ALL modified files (formatted + original changes)
3. Create commit using a HEREDOC for proper formatting:
   ```bash
   git commit -m "$(cat <<'EOF'
   <your commit message here>
   EOF
   )"
   ```
3. Run `git status` after commit to verify success

## Important Rules

- NEVER commit if there are no changes (empty diff)
- Ask user first if committing sensitive files (.env, credentials, etc.)
- Keep subject line under 72 characters
- Use scope when changes are focused on one module
- Body is optional but useful for complex changes
- ALWAYS include the Claude Code attribution footer
