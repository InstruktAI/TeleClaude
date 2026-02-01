---
description: Command - show TeleClaude history via the history script
argument-hint: '[search terms]'
---

# History

You are now the History Search assistant.

## Purpose

Search agent history and provide context around matching entries, including their native session id and file path.

## Inputs

- Search terms: "$ARGUMENTS"

## Outputs

- History output from `~/.teleclaude/scripts/history.py`

## Steps

- Run: `~/.teleclaude/scripts/history.py` --agent {{agent}} "$ARGUMENTS"
