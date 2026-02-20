# Session Output Linkability and Accessibility — Idea

**Date:** 2026-02-20
**Source:** Recent memory (2025-10-30)
**Priority:** Medium (UX friction point)

## Summary

User requested making session output easily accessible via clickable links. Current flow requires manual navigation; desired flow: link at bottom of message leads directly to full output.

## User Request

"Make the output a clickable link. Is that possible in a code block? Place it at the bottom so I can open it immediately."

## Why This Matters

Improves visibility into remote work. Users can quickly inspect full logs without leaving the session interface. Reduces friction for debugging and monitoring.## Pattern

- Server starts and produces output
- Output is large/long
- User needs quick access to full output
- Current: must navigate to find it
- Desired: clickable link embedded in message

## Implementation Notes

- Likely involves session storage/artifact system
- Need to expose URLs in response messages
- Code block formatting + link handling
- Position at bottom of message for discoverability

## Related

- Session lifecycle and artifact storage
- Message formatting and widgets
- Output streaming and buffering
