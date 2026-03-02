# Bug: Personal assistant sessions land in ~/.teleclaude/people/{name}/workspace/ instead of directly in ~/.teleclaude/people/{name}/. The workspace subfolder is unnecessary indirection — the person's folder IS where their personal agent lives. scaffold_personal_workspace() in invite.py creates this extra folder and symlinks AGENTS.master.md into it. Fix: sessions should land in the person's folder directly. The AGENTS.master.md already lives there. Remove the workspace subfolder concept from scaffold_personal_workspace(), update all callers in telegram_adapter.py and discord_adapter.py to use the person folder directly.

## Symptom

Personal assistant sessions land in ~/.teleclaude/people/{name}/workspace/ instead of directly in ~/.teleclaude/people/{name}/. The workspace subfolder is unnecessary indirection — the person's folder IS where their personal agent lives. scaffold_personal_workspace() in invite.py creates this extra folder and symlinks AGENTS.master.md into it. Fix: sessions should land in the person's folder directly. The AGENTS.master.md already lives there. Remove the workspace subfolder concept from scaffold_personal_workspace(), update all callers in telegram_adapter.py and discord_adapter.py to use the person folder directly.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-02

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
