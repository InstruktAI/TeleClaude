# Integration Test Coverage Analysis

**Updated:** 2026-02-05

This document maps integration tests to use cases defined in `tests/E2E_USE_CASES.md`.

---

## Coverage Matrix

| Use Case                                           | Test File                          | Test Name                                                | Status  |
| -------------------------------------------------- | ---------------------------------- | -------------------------------------------------------- | ------- |
| UC-H1: Command success → output delivered          | test_command_e2e.py                | test_short_lived_command                                 | ✅ Full |
| UC-H2: Command failure → error message             | test_command_e2e.py                | test_command_failure_reports_error                       | ✅ Full |
| UC-H3: Long-running command → polling stays active | test_command_e2e.py                | test_long_running_command                                | ✅ Full |
| UC-H4: Agent transcript download                   | test_output_download.py            | test_output_truncation_adds_download_button              | ✅ Full |
| UC-H4: Agent transcript download                   | test_output_download.py            | test_download_full_sends_transcript_and_cleans_temp_file | ✅ Full |
| UC-H5: File upload → path injected                 | test_file_upload.py                | test_file_upload_with_claude_code                        | ✅ Full |
| UC-H5: File upload → path injected                 | test_file_upload.py                | test_file_upload_without_claude_code                     | ✅ Full |
| UC-H6: Feedback cleanup on next input              | test_feedback_cleanup.py           | test_ephemeral_messages_cleaned_on_user_input            | ✅ Full |
| UC-V1: Voice transcription → execute               | test_voice_flow.py                 | test_voice_transcription_executes_command                | ✅ Full |
| UC-V2: Voice transcription failure                 | test_voice_flow.py                 | test_voice_transcription_none_skips_execution            | ✅ Full |
| UC-A1: AI-to-AI session init                       | test_ai_to_ai_session_init_e2e.py  | test_ai_to_ai_session_initialization_with_claude_startup | ✅ Full |
| UC-A2: AI-to-AI command execution                  | test_ai_to_ai_session_init_e2e.py  | test_ai_to_ai_cd_and_claude_commands_execute_in_tmux     | ✅ Full |
| UC-A3: MCP tool surface                            | test_mcp_tools.py                  | test_teleclaude_list_computers (and siblings)            | ✅ Full |
| UC-S1: Close session cleanup                       | test_session_lifecycle.py          | test_close_session_full_cleanup                          | ✅ Full |
| UC-S2: Polling restart                             | test_polling_restart.py            | test_polling_registry_clears_after_exit                  | ✅ Full |
| UC-S3: Process exit detection                      | test_process_exit_detection.py     | test_process_detection_survives_daemon_restart           | ✅ Full |
| UC-M1: Multi-adapter broadcast                     | test_multi_adapter_broadcasting.py | test_last_input_origin_receives_output                   | ✅ Full |
| UC-R1: Redis heartbeat                             | test_redis_heartbeat.py            | test_heartbeat_includes_sessions                         | ✅ Full |
| UC-R2: Redis adapter warmup                        | test_redis_adapter_warmup.py       | test_startup_refreshes_remote_snapshot                   | ✅ Full |
| UC-R3: Cache digest stability                      | test_projects_digest_refresh.py    | test_project_digest_changes_detected                     | ✅ Full |
| UC-CTX: Context selector                           | test_context_selector_e2e.py       | test_context_selector_phase1                             | ✅ Full |
| UC-CLI1: telec docs index                          | test_telec_cli_commands.py         | test_docs_phase1_parses_flags_and_calls_selector         | ✅ Full |
| UC-CLI2: telec docs get                            | test_telec_cli_commands.py         | test_docs_phase2_ignores_filters                         | ✅ Full |
| UC-CLI3: telec sync validate-only                  | test_telec_cli_commands.py         | test_sync_validate_only_calls_sync                       | ✅ Full |
| UC-CLI4: telec init                                | test_telec_cli_commands.py         | test_init_calls_init_project                             | ✅ Full |
| UC-CLI5: telec completion                          | test_telec_cli_commands.py         | test_completion_docs_flags                               | ✅ Full |

---

## Notes

- TUI view snapshots are covered in `tests/unit/test_tui_view_snapshots.py` and map to A/B/C in `tests/E2E_USE_CASES.md`.
- All integration tests run with `daemon_with_mocked_telegram` or isolated Db fixtures; no external side effects.

---

## Execution

```bash
.venv/bin/pytest tests/integration/ -v
```
