# with-session-staleness — Input

Refactor 7 methods that unconditionally need fresh session state to use the with_session decorator pattern. Change signatures from session: Session to session_id: str, apply @with_session, update all callers.

Methods to refactor:
1. discord_adapter._get_output_message_id — currently fetches fresh manually
2. telegram_adapter._get_output_message_id — currently fetches fresh manually
3. whatsapp_adapter._get_output_message_id — currently fetches fresh manually
4. ui_adapter._get_badge_sent — currently fetches fresh manually
5. threaded_output._sync_threaded_session_state — currently fetches fresh manually
6. _helpers._has_active_output_message — trusts stale passed-in session (BLOCKS DISCORD TURN 2 OUTPUT)
7. _helpers._resolve_hook_actor_name — trusts stale passed-in session

Root cause: migration from adapter_metadata (shared mutable in-memory reference) to origin_metadata (dict copy per read) broke implicit freshness. The with_session decorator makes freshness explicit and contractual.

CRITICAL: #6 is the immediate blocker for Discord threaded output on turn 2+. The stale session causes _has_active_output_message to return False, which prevents turn break detection, which prevents digest invalidation, which suppresses delivery.
