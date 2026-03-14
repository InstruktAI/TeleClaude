# Implementation Plan: chartest-peripherals

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/channels/api_routes.py` → `tests/unit/channels/test_api_routes.py`
- [ ] Characterize `teleclaude/channels/consumer.py` → `tests/unit/channels/test_consumer.py`
- [ ] Characterize `teleclaude/channels/publisher.py` → `tests/unit/channels/test_publisher.py`
- [ ] Characterize `teleclaude/channels/worker.py` → `tests/unit/channels/test_worker.py`
- [ ] Characterize `teleclaude/chiptunes/favorites.py` → `tests/unit/chiptunes/test_favorites.py`
- [ ] Characterize `teleclaude/chiptunes/manager.py` → `tests/unit/chiptunes/test_manager.py`
- [ ] Characterize `teleclaude/chiptunes/player.py` → `tests/unit/chiptunes/test_player.py`
- [ ] Characterize `teleclaude/chiptunes/sid_cpu.py` → `tests/unit/chiptunes/test_sid_cpu.py`
- [ ] Characterize `teleclaude/chiptunes/sid_parser.py` → `tests/unit/chiptunes/test_sid_parser.py`
- [ ] Characterize `teleclaude/chiptunes/sid_renderer.py` → `tests/unit/chiptunes/test_sid_renderer.py`
- [ ] Characterize `teleclaude/chiptunes/worker.py` → `tests/unit/chiptunes/test_worker.py`
- [ ] Characterize `teleclaude/config/loader.py` → `tests/unit/config/test_loader.py`
- [ ] Characterize `teleclaude/config/runtime_settings.py` → `tests/unit/config/test_runtime_settings.py`
- [ ] Characterize `teleclaude/config/schema.py` → `tests/unit/config/test_schema.py`
- [ ] Characterize `teleclaude/content_scaffold.py` → `tests/unit/test_content_scaffold.py`
- [ ] Characterize `teleclaude/context_selector.py` → `tests/unit/test_context_selector.py`
- [ ] Characterize `teleclaude/cron/discovery.py` → `tests/unit/cron/test_discovery.py`
- [ ] Characterize `teleclaude/cron/job_recipients.py` → `tests/unit/cron/test_job_recipients.py`
- [ ] Characterize `teleclaude/cron/notification_scan.py` → `tests/unit/cron/test_notification_scan.py`
- [ ] Characterize `teleclaude/cron/state.py` → `tests/unit/cron/test_state.py`
- [ ] Characterize `teleclaude/daemon.py` → `tests/unit/test_daemon.py`
- [ ] Characterize `teleclaude/daemon_event_platform.py` → `tests/unit/test_daemon_event_platform.py`
- [ ] Characterize `teleclaude/daemon_hook_outbox.py` → `tests/unit/test_daemon_hook_outbox.py`
- [ ] Characterize `teleclaude/daemon_session.py` → `tests/unit/test_daemon_session.py`
- [ ] Characterize `teleclaude/deployment/executor.py` → `tests/unit/deployment/test_executor.py`
- [ ] Characterize `teleclaude/deployment/handler.py` → `tests/unit/deployment/test_handler.py`
- [ ] Characterize `teleclaude/deployment/migration_runner.py` → `tests/unit/deployment/test_migration_runner.py`
- [ ] Characterize `teleclaude/docs_index.py` → `tests/unit/test_docs_index.py`
- [ ] Characterize `teleclaude/entrypoints/macos_setup.py` → `tests/unit/entrypoints/test_macos_setup.py`
- [ ] Characterize `teleclaude/entrypoints/send_telegram.py` → `tests/unit/entrypoints/test_send_telegram.py`
- [ ] Characterize `teleclaude/entrypoints/youtube_sync_subscriptions.py` → `tests/unit/entrypoints/test_youtube_sync_subscriptions.py`
- [ ] Characterize `teleclaude/helpers/agent_cli.py` → `tests/unit/helpers/test_agent_cli.py`
- [ ] Characterize `teleclaude/helpers/agent_types.py` → `tests/unit/helpers/test_agent_types.py`
- [ ] Characterize `teleclaude/helpers/git_repo_helper.py` → `tests/unit/helpers/test_git_repo_helper.py`
- [ ] Characterize `teleclaude/helpers/youtube/refresh_cookies.py` → `tests/unit/helpers/youtube/test_refresh_cookies.py`
- [ ] Characterize `teleclaude/helpers/youtube_helper/_models.py` → `tests/unit/helpers/youtube_helper/test__models.py`
- [ ] Characterize `teleclaude/helpers/youtube_helper/_parsers.py` → `tests/unit/helpers/youtube_helper/test__parsers.py`
- [ ] Characterize `teleclaude/helpers/youtube_helper/_utils.py` → `tests/unit/helpers/youtube_helper/test__utils.py`
- [ ] Characterize `teleclaude/history/search.py` → `tests/unit/history/test_search.py`
- [ ] Characterize `teleclaude/install/install_hooks.py` → `tests/unit/install/test_install_hooks.py`
- [ ] Characterize `teleclaude/invite.py` → `tests/unit/test_invite.py`
- [ ] Characterize `teleclaude/logging_config.py` → `tests/unit/test_logging_config.py`
- [ ] Characterize `teleclaude/mlx_utils.py` → `tests/unit/test_mlx_utils.py`
- [ ] Characterize `teleclaude/output_projection/conversation_projector.py` → `tests/unit/output_projection/test_conversation_projector.py`
- [ ] Characterize `teleclaude/output_projection/models.py` → `tests/unit/output_projection/test_models.py`
- [ ] Characterize `teleclaude/output_projection/serializers.py` → `tests/unit/output_projection/test_serializers.py`
- [ ] Characterize `teleclaude/output_projection/terminal_live_projector.py` → `tests/unit/output_projection/test_terminal_live_projector.py`
- [ ] Characterize `teleclaude/paths.py` → `tests/unit/test_paths.py`
- [ ] Characterize `teleclaude/project_manifest.py` → `tests/unit/test_project_manifest.py`
- [ ] Characterize `teleclaude/project_setup/domain_seeds.py` → `tests/unit/project_setup/test_domain_seeds.py`
- [ ] Characterize `teleclaude/project_setup/enrichment.py` → `tests/unit/project_setup/test_enrichment.py`
- [ ] Characterize `teleclaude/project_setup/git_filters.py` → `tests/unit/project_setup/test_git_filters.py`
- [ ] Characterize `teleclaude/project_setup/git_repo.py` → `tests/unit/project_setup/test_git_repo.py`
- [ ] Characterize `teleclaude/project_setup/gitattributes.py` → `tests/unit/project_setup/test_gitattributes.py`
- [ ] Characterize `teleclaude/project_setup/help_desk_bootstrap.py` → `tests/unit/project_setup/test_help_desk_bootstrap.py`
- [ ] Characterize `teleclaude/project_setup/hooks.py` → `tests/unit/project_setup/test_hooks.py`
- [ ] Characterize `teleclaude/project_setup/init_flow.py` → `tests/unit/project_setup/test_init_flow.py`
- [ ] Characterize `teleclaude/project_setup/macos_setup.py` → `tests/unit/project_setup/test_macos_setup.py`
- [ ] Characterize `teleclaude/project_setup/sync.py` → `tests/unit/project_setup/test_sync.py`
- [ ] Characterize `teleclaude/required_reads.py` → `tests/unit/test_required_reads.py`
- [ ] Characterize `teleclaude/resource_validation/_models.py` → `tests/unit/resource_validation/test__models.py`
- [ ] Characterize `teleclaude/resource_validation/_snippet.py` → `tests/unit/resource_validation/test__snippet.py`
- [ ] Characterize `teleclaude/runtime/binaries.py` → `tests/unit/runtime/test_binaries.py`
- [ ] Characterize `teleclaude/services/discord.py` → `tests/unit/services/test_discord.py`
- [ ] Characterize `teleclaude/services/email.py` → `tests/unit/services/test_email.py`
- [ ] Characterize `teleclaude/services/headless_snapshot_service.py` → `tests/unit/services/test_headless_snapshot_service.py`
- [ ] Characterize `teleclaude/services/maintenance_service.py` → `tests/unit/services/test_maintenance_service.py`
- [ ] Characterize `teleclaude/services/monitoring_service.py` → `tests/unit/services/test_monitoring_service.py`
- [ ] Characterize `teleclaude/services/telegram.py` → `tests/unit/services/test_telegram.py`
- [ ] Characterize `teleclaude/services/whatsapp.py` → `tests/unit/services/test_whatsapp.py`
- [ ] Characterize `teleclaude/slug.py` → `tests/unit/test_slug.py`
- [ ] Characterize `teleclaude/snippet_validation.py` → `tests/unit/test_snippet_validation.py`
- [ ] Characterize `teleclaude/stt/backends/mlx_parakeet.py` → `tests/unit/stt/backends/test_mlx_parakeet.py`
- [ ] Characterize `teleclaude/stt/backends/openai_whisper.py` → `tests/unit/stt/backends/test_openai_whisper.py`
- [ ] Characterize `teleclaude/sync.py` → `tests/unit/test_sync.py`
- [ ] Characterize `teleclaude/tagging/youtube.py` → `tests/unit/tagging/test_youtube.py`
- [ ] Characterize `teleclaude/tts/audio_focus.py` → `tests/unit/tts/test_audio_focus.py`
- [ ] Characterize `teleclaude/tts/backends/elevenlabs.py` → `tests/unit/tts/backends/test_elevenlabs.py`
- [ ] Characterize `teleclaude/tts/backends/macos_say.py` → `tests/unit/tts/backends/test_macos_say.py`
- [ ] Characterize `teleclaude/tts/backends/mlx_tts.py` → `tests/unit/tts/backends/test_mlx_tts.py`
- [ ] Characterize `teleclaude/tts/backends/openai_tts.py` → `tests/unit/tts/backends/test_openai_tts.py`
- [ ] Characterize `teleclaude/tts/backends/pyttsx3_tts.py` → `tests/unit/tts/backends/test_pyttsx3_tts.py`
- [ ] Characterize `teleclaude/tts/manager.py` → `tests/unit/tts/test_manager.py`
- [ ] Characterize `teleclaude/tts/models.py` → `tests/unit/tts/test_models.py`
- [ ] Characterize `teleclaude/tts/queue_runner.py` → `tests/unit/tts/test_queue_runner.py`
- [ ] Characterize `teleclaude/types/commands.py` → `tests/unit/types/test_commands.py`
- [ ] Characterize `teleclaude/types/system.py` → `tests/unit/types/test_system.py`
- [ ] Characterize `teleclaude/types/todos.py` → `tests/unit/types/test_todos.py`
- [ ] Characterize `teleclaude/utils/markdown.py` → `tests/unit/utils/test_markdown.py`
- [ ] Characterize `teleclaude/utils/transcript_discovery.py` → `tests/unit/utils/test_transcript_discovery.py`
- [ ] Characterize `teleclaude/utils/transcript/_block_renderers.py` → `tests/unit/utils/transcript/test__block_renderers.py`
- [ ] Characterize `teleclaude/utils/transcript/_extraction.py` → `tests/unit/utils/transcript/test__extraction.py`
- [ ] Characterize `teleclaude/utils/transcript/_iterators.py` → `tests/unit/utils/transcript/test__iterators.py`
- [ ] Characterize `teleclaude/utils/transcript/_parsers.py` → `tests/unit/utils/transcript/test__parsers.py`
- [ ] Characterize `teleclaude/utils/transcript/_rendering.py` → `tests/unit/utils/transcript/test__rendering.py`
- [ ] Characterize `teleclaude/utils/transcript/_tool_calls.py` → `tests/unit/utils/transcript/test__tool_calls.py`
- [ ] Characterize `teleclaude/utils/transcript/_utils.py` → `tests/unit/utils/transcript/test__utils.py`
