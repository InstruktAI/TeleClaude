---
description: Analyze a screenshot provided by the user or the latest screenshot
argument-hint: '[screenshot-path]'
---

# Screenshot Analyze

You are now the Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/concept/reviewer.md

## Purpose

Analyze a screenshot and report issues or observations.

## Inputs

- Optional screenshot path: "$ARGUMENTS"
- If no path is provided, use the latest screenshot in `~/Library/CloudStorage/Dropbox/Screenshots`

## Outputs

- A concise analysis of what is visible and any issues found

## Steps

- If a screenshot path is provided, use it. Otherwise run:
  `ls -t ~/Library/CloudStorage/Dropbox/Screenshots | head -n 1`
- Use the Read tool to view the screenshot.
- Identify problems or details visible in the screenshot.
- Explain findings clearly and concisely.
