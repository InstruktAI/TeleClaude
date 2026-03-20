# Bug: Admin TUI sessions routed to Discord help desk instead of project/sessions channel

## Symptom

Admin TUI sessions routed to Discord help desk instead of project/sessions channel

## Detail

Identity resolver in core/identity.py:resolve() has no handler for origin='api'. Falls through to default HUMAN_ROLE_CUSTOMER (line 214). This causes Discord adapter's _is_customer_session() to return True, routing to help_desk_channel_id. Fix: add 'api' origin handler that preserves the authenticated caller's role, or defaults to admin for API-authenticated callers. Key files: teleclaude/core/identity.py (resolve method), teleclaude/adapters/discord/channel_ops.py (_resolve_target_forum, _is_customer_session), teleclaude/api/sessions_routes.py:388.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-20

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
