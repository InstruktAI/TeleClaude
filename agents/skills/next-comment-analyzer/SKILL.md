---
name: next-comment-analyzer
description: Analyze code comments for accuracy, completeness, and long-term maintainability. Use after adding documentation, before finalizing PRs with comment changes, or when reviewing existing comments for technical debt.
---

This skill analyzes code comments for accuracy, completeness, and long-term maintainability. It treats comments with healthy skepticism because inaccurate or outdated comments create technical debt that compounds over time.

## Context to Gather

Before analyzing, read:

- The code that comments describe
- Related code to understand context
- Existing documentation patterns in the project

## Core Mission

Protect codebases from comment rot by ensuring every comment adds genuine value and remains accurate as code evolves. Analyze comments through the lens of a developer encountering the code months or years later, potentially without context about the original implementation.

## Analysis Process

### 1. Verify Factual Accuracy

Cross-reference every claim in the comment against the actual code implementation:

- Function signatures match documented parameters and return types
- Described behavior aligns with actual code logic
- Referenced types, functions, and variables exist and are used correctly
- Edge cases mentioned are actually handled in the code
- Performance characteristics or complexity claims are accurate

### 2. Assess Completeness

Evaluate whether the comment provides sufficient context without being redundant:

- Critical assumptions or preconditions are documented
- Non-obvious side effects are mentioned
- Important error conditions are described
- Complex algorithms have their approach explained
- Business logic rationale is captured when not self-evident

### 3. Evaluate Long-term Value

Consider the comment's utility over the codebase's lifetime:

- Comments that merely restate obvious code should be flagged for removal
- Comments explaining 'why' are more valuable than those explaining 'what'
- Comments that will become outdated with likely code changes should be reconsidered
- Comments should be written for the least experienced future maintainer
- Avoid comments that reference temporary states or transitional implementations

### 4. Identify Misleading Elements

Actively search for ways comments could be misinterpreted:

- Ambiguous language that could have multiple meanings
- Outdated references to refactored code
- Assumptions that may no longer hold true
- Examples that don't match current implementation
- TODOs or FIXMEs that may have already been addressed

### 5. Suggest Improvements

Provide specific, actionable feedback:

- Rewrite suggestions for unclear or inaccurate portions
- Recommendations for additional context where needed
- Clear rationale for why comments should be removed
- Alternative approaches for conveying the same information

## Output Format

**Summary**: Brief overview of the comment analysis scope and findings

**Critical Issues**: Comments that are factually incorrect or highly misleading

- Location: [file:line]
- Issue: [specific problem]
- Suggestion: [recommended fix]

**Improvement Opportunities**: Comments that could be enhanced

- Location: [file:line]
- Current state: [what's lacking]
- Suggestion: [how to improve]

**Recommended Removals**: Comments that add no value or create confusion

- Location: [file:line]
