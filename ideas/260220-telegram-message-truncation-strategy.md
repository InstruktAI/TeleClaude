# Telegram Message Truncation Strategy

**Date:** 2026-02-20
**Source:** Lifelog analysis from 10/30 and 12/02 sessions

## Problem

Repeated friction when terminal output exceeds Telegram's message length limits:

- Messages are truncated at the top, losing context
- User cannot see full command output from start to finish
- Large outputs need manual management; current approach loses data

## Solution Pattern

When output approaches or exceeds adapter message limits:

1. Keep full buffer internally (DB or text file)
2. Display truncated version in Telegram with clickable link to full text
3. Link opens in browser as plain text (text-only content)
4. User can access complete output on demand

## Implementation Notes

- Track message length against adapter limits
- Truncate from top when necessary (keep latest output visible)
- Store full buffer separately for link access
- Mark truncation point clearly in displayed message
- Use existing message edit pattern to update as new output arrives

## Related Discussions

- Telegram bridge message handling
- Output buffering in Cloud terminal integration
- Message size limits per adapter
