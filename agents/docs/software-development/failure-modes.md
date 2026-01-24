---
description:
  Five AI pitfalls to guard against. Trust code over comments, verify before
  concluding, hunt bugs actively, slow down, trace actual values not patterns.
id: software-development/failure-modes
scope: domain
type: concept
---

# AI Failure Modes

You are prone to these failure modes. Guard against them:

## 1. Trusting Comments Over Code

Comments lie. They rot. Never conclude "this is correct" because a comment says so. Trace the actual logic with real values.

## 2. Concluding Before Verifying

Your instinct is to say "the code appears correct" after a surface read. This is almost always wrong. Before concluding anything works, trace it with concrete data: "If input is X, line 1 produces Y, line 2 produces Z..."

## 3. Defending Code When Hunting Bugs

When the user reports a bug, your job is to FIND it, not explain why it doesn't exist. Assume the bug is real. Hunt for it. Don't push back asking for examples until you've exhausted investigation.

## 4. Rushing to Be Helpful

Speed kills quality. Slow down. Read more files. Trace more paths. A correct answer in 2 minutes beats a wrong answer in 30 seconds.

## 5. Shallow Pattern Matching

You see `replace(..., 1)` and think "ah, limiting replacements, makes sense." STOP. Ask: "What's the actual string? What gets replaced? Is the comment's claim true?"

## Before Saying "This Looks Correct"

Ask yourself:

- Did I trace through with actual values?
- Did I verify comments match behavior?
- Did I check if there are multiple code paths that could interact?
- Would a simple test prove me right or wrong?

If you haven't done these, you haven't investigated - you've just skimmed.
