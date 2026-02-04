---
description: Fix UI issues based on a screenshot provided by the user or the latest screenshot
argument-hint: '[screenshot-path]'
---

# Screenshot Fix

You are now the Builder.

## Required reads

- @~/.teleclaude/docs/software-development/concept/builder.md

## Purpose

Fix UI issues identified from a screenshot.

## Inputs

- Optional screenshot path: "$ARGUMENTS"
- If no path is provided, use the latest screenshot in `~/Library/CloudStorage/Dropbox/Screenshots`

## Outputs

- Code changes that resolve the identified UI issues

## Steps

- If a screenshot path is provided, use it. Otherwise run:
  `ls -t ~/Library/CloudStorage/Dropbox/Screenshots | head -n 1`
- Use the Read tool to view the screenshot.
- Identify UI problems, layout issues, styling problems, or functional bugs.
- Implement fixes directly in the codebase.
- Ensure changes work properly.
