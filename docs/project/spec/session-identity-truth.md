---
id: 'project/spec/session-identity-truth'
type: 'spec'
scope: 'project'
description: 'Canonical truth for session identity, mapping, and recovery across managed and headless routes.'
---

# Session Identity Truth — Spec

## Why this exists

Session identity confusion causes the worst operational bugs:

- hooks linked to the wrong session,
- headless turns split across many session rows,
- "cannot recover transcript" errors,
- notifications sent to the wrong place.

This document is the single truth for how TeleClaude decides "which session this hook belongs to."

## Two real routes (and only two)

### Route A: Managed TeleClaude session (tmux-backed)

This is the normal route for sessions launched by TeleClaude.

How identity is resolved:

1. TeleClaude creates a session row.
2. TeleClaude creates per-session temp directory.
3. TeleClaude writes session marker file (`teleclaude_session_id`) in that temp directory.
4. Hooks from that running process reuse that TeleClaude session id directly.

Result:

- Identity is immediate and stable.
- No session map lookup is needed for normal operation.

### Route B: Headless/standalone hook process

This is used when a hook arrives without managed TeleClaude session context.

How identity is resolved:

1. Receiver extracts native identity from payload (native session id, transcript path).
2. Receiver checks native-to-TeleClaude map file at `~/.teleclaude/session_map.json`.
3. Receiver checks database by native session id.
4. If found, reuse existing TeleClaude session id.
5. If not found, mint new TeleClaude session id and let daemon create headless session row.

Result:

- Headless sessions can survive daemon restarts and still map correctly.
- Native identity is authoritative for this route.

## Source-of-truth fields

| Field               | Meaning                         | Where stored                               | Who writes it               |
| ------------------- | ------------------------------- | ------------------------------------------ | --------------------------- |
| `session_id`        | TeleClaude session identity     | `sessions.session_id`, hook payload        | Core + receiver             |
| `native_session_id` | Native agent identity           | `sessions.native_session_id`, hook payload | Receiver + coordinator      |
| `native_log_file`   | Native transcript path          | `sessions.native_log_file`, hook payload   | Receiver + coordinator      |
| session marker file | Managed-session identity marker | per-session TMP directory                  | Session launcher/tmux setup |
| session map         | Native→TeleClaude mapping cache | `~/.teleclaude/session_map.json`           | Hook receiver               |

## Authority rules

- Managed route: session marker file wins.
- Headless route: native identity mapping wins.
- If both exist, managed marker is trusted for managed sessions; native identity is used for standalone hooks.

## Recovery behavior

### After daemon restart

- Managed sessions: identity remains stable if process/TMP context survives.
- Headless sessions: mapping file + DB native fields allow reassociation.

### If native transcript path is missing

- System may still continue with reduced features.
- Session data retrieval from native transcript can fail until path is discovered or refreshed.

## Failure modes and fixes

| Problem                                            | Typical cause                                        | What to do first                                                                    |
| -------------------------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Hook attached to wrong session                     | stale/incorrect mapping path or stale marker context | verify route (managed vs headless), inspect mapping entry and session native fields |
| Many tiny headless sessions for one native session | mapping not persisted/reused                         | check map file writes and DB native fields on first hook                            |
| `get_session_data` returns nothing for headless    | missing `native_log_file`                            | verify latest hook payload carried transcript path; verify session row updated      |
| Session cannot be resumed correctly                | wrong or missing native id on session                | verify `native_session_id` in session row before resume flow                        |

## Operator checklist: identity incidents

1. Confirm route: managed vs headless.
2. Check session row fields (`session_id`, `native_session_id`, `native_log_file`, `lifecycle_status`).
3. Check mapping file entry for native id.
4. Verify latest hook payload includes expected native identity.
5. Restart daemon only after capturing evidence.

## Change safety rule

Any code change that alters identity extraction, mapping, or marker behavior must update this file in the same PR.
