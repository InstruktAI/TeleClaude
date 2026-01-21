---
argument-hint: "[branch-name]"
description: Create a git worktree in the trees/ directory
---

# Purpose: Create GitHub Issues from Implementation Plan

You are tasked with converting an implementation plan into GitHub issues for parallel execution.
The process we follow is next-work, and this is an extension to work out the task via GitHub issues.
The objective is to ONLY WORK ON GIHUB ISSUES created from the implementation plan.

## Arguments

Todo's subject slug: "$ARGUMENTS"

(Required, slug of the todos/{subject-slug}/implementation-plan.md file to analyze.)

## Context

The user has an implementation plan (likely in `todos/{subject-slug}/implementation-plan.md` or similar) with multiple steps that can be executed in parallel or sequentially based on dependencies. If NO SUBJECT WAS GIVEN, you MUST look in `todos/roadmap.md` for the first todo item that is either in progress or unstarted, and find its implementation plan.

## Your Task

Execute this in **TWO PHASES**:

## PHASE 1: Analysis & Approval

1. **Read the implementation plan** from the file provided by the user (or ask which file to analyze)

2. **Parse into atomic work items**:
   - Each STEP becomes a potential issue
   - Identify sub-tasks within steps that could be split
   - Look for "Prerequisites" to determine dependencies

3. **Determine dependencies**:
   - Map which steps depend on which other steps
   - Identify steps that can run in parallel (no shared dependencies)
   - Create a dependency graph

4. **Present to user for approval** in this format:

   ```markdown
   ## Proposed GitHub Issues

   ### Parallel Track 1 (can start immediately)

   - [ ] **Issue #1**: Create samples/ Directory (1hr)
     - Labels: `enhancement`
     - Dependencies: none
     - Description: Create sample files for initialization (env, traefik.yml, secrets, example-project)
     - **Note**: Skip SOPS installation issue - must be done locally

   ### Sequential Track (after samples created)

   - [ ] **Issue #2**: Initialize Secrets Submodule (45min)
     - Labels: `enhancement`
     - Dependencies: requires SOPS setup (done locally)
     - Description: Setup secrets/ with SOPS, git hooks, structure

   - [ ] **Issue #3**: Initialize Projects Submodule (30min)
     - Labels: `enhancement`
     - Dependencies: none (repos already created)
     - Description: Setup projects/ structure

   ### Parallel Track 2 (after submodules)

   - [ ] **Issue #4**: Extract Secrets Script (1-2hrs)
     - Labels: `enhancement`
     - Dependencies: #2
     - Description: Create script to extract secrets from db.yml

   - [ ] **Issue #5**: Create itsup init Command (2hrs)
     - Labels: `enhancement`
     - Dependencies: #1
     - Description: Implement initialization command that copies samples

   ... (continue for all steps)

   ## Parallelization Summary

   - **Immediate start**: 2 issues (no dependencies)
   - **After track 1**: 2 issues
   - **After track 2**: 5 issues
   - **Total estimated time (parallel)**: ~X hours (vs Y hours sequential)
   ```

5. **Wait for user approval** before proceeding to Phase 2

---

## PHASE 2: GitHub Issue Creation

Once the user approves the plan, create GitHub issues using the `gh` tool:

For each issue:

1. **Create the issue** with:

   ```text
   Title: <Clear, actionable title>

   Body:
   ## Objective
   <What needs to be accomplished>

   ## Prerequisites
   <List of issue numbers that must be completed first>
   <If none, state "None - can start immediately">

   ## Implementation Steps
   <Detailed, actionable steps from the implementation plan>
   <Include code snippets, commands, file paths>

   ## Success Criteria
   <Checklist of what defines "done">
   - [ ] Criterion 1
   - [ ] Criterion 2

   ## Files to Modify/Create
   <List of files that will be touched>

   ## Testing
   <How to verify the implementation works>

   ## Instructions for Claude (GitHub Actions)

   This issue is designed for automated implementation via GitHub Actions with Claude Code.

   **Setup:**
   1. Read the implementation steps above
   2. Read the files listed in "Files to Modify/Create"
   3. Understand the success criteria

   **Execution:**
   1. Implement the changes exactly as specified
   2. Run all tests mentioned in "Testing" section
   3. Verify all success criteria are met
   4. Create a PR with:
      - Title: "Closes #<issue-number>: <title>"
      - Description: Summary of changes + success criteria checklist
      - Request review from @<maintainer>

   **Important:**
   - DO NOT proceed if prerequisites (issues #X, #Y) are not closed
   - DO NOT add extra features beyond the scope
   - DO mark PR as draft if any success criteria fail
   - DO add "[NEEDS REVIEW]" label if uncertain about implementation

   ## Estimated Time
   <From implementation plan>

   ## Commit Message
   <Suggested commit message from implementation plan>
   ```

2. **Add labels** (use existing labels only):
   - `enhancement` - for new features
   - `bug` - for bug fixes
   - `documentation` - for docs updates
   - `question` - for tasks needing clarification
   - `help wanted` - for complex tasks needing extra attention
   - Use sparingly - only 1-2 labels per issue

3. **Set dependencies** (in issue body, as GitHub doesn't have native dependency fields)

4. **Report progress** to user:

   ```text
   Created issue #123: Setup SOPS Infrastructure
   Created issue #124: Create samples/ Directory
   ...

   ✓ Created 13 issues
   ```

---

## Important Notes

- **Be atomic**: Each issue should be independently completable
- **Be explicit**: Claude in GitHub Actions needs crystal-clear instructions
- **Be testable**: Each issue must have clear success criteria
- **Track dependencies**: Use issue numbers to track blocking relationships
- **Estimate conservatively**: Time estimates help with planning

## Example Dependency Graph

```text
#1 (SOPS) ─┬─> #3 (Repos) ──> #4 (Secrets Submodule) ──> #5 (Extract Secrets)
           │                                            └──> #8 (Migration Script)
           └─> #6 (itsup init) ──> #11 (CLI)

#2 (samples/) ──> #6 (itsup init)

#7 (Projects Submodule) ──> #8 (Migration)

#8 (Migration) ──> #9 (lib/data.py)
#9 (lib/data.py) ──> #10 (write-artifacts.py)
#10 (write-artifacts.py) ──> #11 (CLI)

#11 (CLI) ──> #12 (Docs)
#12 (Docs) ──> #13 (Cleanup)
```

---

## 🚨 CRITICAL RULES (ADHERE AT ALL COSTS!)

### Only Use Existing GitHub Labels

- GitHub repos have standard labels already (bug, enhancement, documentation, etc.)
- **NEVER create new labels** - label sprawl is a signalling problem
- Use existing labels sparingly as signals, not information reference
- Common existing labels: `bug`, `enhancement`, `documentation`, `question`, `help wanted`

### Do Not Create Issues For Local Setup Tasks

- **NEVER create issues for installing dependencies** (SOPS, age, npm, python packages, etc.)
- **NEVER create issues for local environment setup** (generating keys, configuring local machine)
- **NEVER:** create issues that require sudo/system access
- These tasks MUST be done locally by the user, not in CI/GitHub Actions
- Only create issues for **code changes** that can be automated in CI

### Focus On Automatable Tasks

- ✅ Creating files, writing code, updating documentation
- ✅ Running tests, validation, linting
- ✅ Refactoring, migration scripts
- ❌ Installing system packages, generating local secrets
- ❌ Configuring local user environment
- ❌ Tasks requiring interactive prompts or manual review
