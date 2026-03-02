# Bug: telec sessions end does not support 'self' as a session_id alias. Agents must use the incantation cat $TMPDIR/teleclaude_session_id to discover their own session ID before they can end themselves. Add 'self' resolution to telec sessions end ONLY — no other subcommand needs it. When session_id is 'self', resolve it to the contents of $TMPDIR/teleclaude_session_id. Update the -h output for the end subcommand to document 'self' as a valid value. The telec-cli spec baseline already auto-propagates via @exec: telec sessions -h, so no separate doc work is needed once the CLI is updated.

## Symptom

telec sessions end does not support 'self' as a session_id alias. Agents must use the incantation cat $TMPDIR/teleclaude_session_id to discover their own session ID before they can end themselves. Add 'self' resolution to telec sessions end ONLY — no other subcommand needs it. When session_id is 'self', resolve it to the contents of $TMPDIR/teleclaude_session_id. Update the -h output for the end subcommand to document 'self' as a valid value. The telec-cli spec baseline already auto-propagates via @exec: telec sessions -h, so no separate doc work is needed once the CLI is updated.

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
