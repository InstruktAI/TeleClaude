# tui-chiptunes-resource-leaks — Input

Terminal freezes after 1-2 hours with chiptunes enabled. Three fixes: (1) Prune _last_output_summary in sessions.py update_data() — unbounded dict growth blocks event loop during state serialization. (2) Fix resume event bug in player.py:300-316 — failed _open_stream() returns early without setting _resume_event, leaving emulation thread in zombie spin loop. (3) Log warning on thread join timeout in player.py:280-281 for observability. Out of scope: WS broadcast dedup, animation buffers, audio sidecar.
