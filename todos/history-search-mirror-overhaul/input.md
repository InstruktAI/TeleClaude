# history-search-mirror-overhaul — Input


History search and mirror overhaul.

Objective:
Make telec history search a trustworthy session-discovery tool across historical and live mirrored sessions.

Agreed output contract:
One session block per result, not a table.

Started: <timestamp_start>
Last Active: <updated_at>
Agent: <agent>
TeleClaude Session ID: <teleclaude_session_id>
Native Session ID: <native_session_id>
Human Email: <human_email>   # admin-only when present
Human Role: <human_role>     # admin-only, inferred from human_email

Summary:
<multiline summary>

Context:
- "<query-centered snippet>"
- "<query-centered snippet>"
- "<query-centered snippet>"

---

Agreements:
- Summary is first-class and stored on the mirror.
- Context is computed at search time and must be multiple match-centered snippets, not one collapsed field.
- Started comes from mirror timestamp_start.
- Last Active comes from mirror updated_at by contract.
- Human Role is inferred at render time from human_email; it is not stored in mirrors.
- No identity_key in output.
- No subagent runs in history search results at all.
- Live sessions must become searchable after each completed turn.

Required work:
1. Finish identity prerequisites so human provenance is trustworthy.
   - edge-session-creation
   - identity-origin-cleanup-final
2. Exclude subagent transcripts from mirror ingestion and reconciliation.
3. Make mirror identity fields explicit:
   - teleclaude_session_id
   - native_session_id
   - keep started/updated_at/summary/human_email
4. Fix Codex native session ID extraction so native IDs are correct.
5. Rewrite telec history search output to the per-session block format above.
6. Upgrade context generation to return multiple useful query-centered snippets per session.
7. Close the near-real-time gap so delayed transcript binding also triggers immediate mirror refresh.
8. Clean existing bad mirror rows created from subagents or wrong identifier extraction.

Acceptance criteria:
- History search returns the agreed session-block output.
- Subagent runs are absent from results.
- Human email is reliable for human-driven sessions.
- Human role is rendered correctly for admin viewers.
- Both TeleClaude and native session IDs are explicit and correct.
- Summary is present.
- Context shows multiple relevant snippets.
- Completed turns become searchable near-real-time.

