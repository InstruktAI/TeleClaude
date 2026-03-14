# Input: chartest-peripherals

Characterization tests for peripheral systems.

**Recommended agent:** codex

## Source files to characterize

- `teleclaude/channels/api_routes.py`
- `teleclaude/channels/consumer.py`
- `teleclaude/channels/publisher.py`
- `teleclaude/channels/worker.py`
- `teleclaude/chiptunes/favorites.py`
- `teleclaude/chiptunes/manager.py`
- `teleclaude/chiptunes/player.py`
- `teleclaude/chiptunes/sid_cpu.py`
- `teleclaude/chiptunes/sid_parser.py`
- `teleclaude/chiptunes/sid_renderer.py`
- `teleclaude/chiptunes/worker.py`
- `teleclaude/config/loader.py`
- `teleclaude/config/runtime_settings.py`
- `teleclaude/config/schema.py`
- `teleclaude/content_scaffold.py`
- `teleclaude/context_selector.py`
- `teleclaude/cron/discovery.py`
- `teleclaude/cron/job_recipients.py`
- `teleclaude/cron/notification_scan.py`
- `teleclaude/cron/state.py`
- `teleclaude/daemon.py`
- `teleclaude/daemon_event_platform.py`
- `teleclaude/daemon_hook_outbox.py`
- `teleclaude/daemon_session.py`
- `teleclaude/deployment/executor.py`
- `teleclaude/deployment/handler.py`
- `teleclaude/deployment/migration_runner.py`
- `teleclaude/docs_index.py`
- `teleclaude/entrypoints/macos_setup.py`
- `teleclaude/entrypoints/send_telegram.py`
- `teleclaude/entrypoints/youtube_sync_subscriptions.py`
- `teleclaude/helpers/agent_cli.py`
- `teleclaude/helpers/agent_types.py`
- `teleclaude/helpers/git_repo_helper.py`
- `teleclaude/helpers/youtube/refresh_cookies.py`
- `teleclaude/helpers/youtube_helper/_models.py`
- `teleclaude/helpers/youtube_helper/_parsers.py`
- `teleclaude/helpers/youtube_helper/_utils.py`
- `teleclaude/history/search.py`
- `teleclaude/install/install_hooks.py`
- `teleclaude/invite.py`
- `teleclaude/logging_config.py`
- `teleclaude/mlx_utils.py`
- `teleclaude/output_projection/conversation_projector.py`
- `teleclaude/output_projection/models.py`
- `teleclaude/output_projection/serializers.py`
- `teleclaude/output_projection/terminal_live_projector.py`
- `teleclaude/paths.py`
- `teleclaude/project_manifest.py`
- `teleclaude/project_setup/domain_seeds.py`
- `teleclaude/project_setup/enrichment.py`
- `teleclaude/project_setup/git_filters.py`
- `teleclaude/project_setup/git_repo.py`
- `teleclaude/project_setup/gitattributes.py`
- `teleclaude/project_setup/help_desk_bootstrap.py`
- `teleclaude/project_setup/hooks.py`
- `teleclaude/project_setup/init_flow.py`
- `teleclaude/project_setup/macos_setup.py`
- `teleclaude/project_setup/sync.py`
- `teleclaude/required_reads.py`
- `teleclaude/resource_validation/_models.py`
- `teleclaude/resource_validation/_snippet.py`
- `teleclaude/runtime/binaries.py`
- `teleclaude/services/discord.py`
- `teleclaude/services/email.py`
- `teleclaude/services/headless_snapshot_service.py`
- `teleclaude/services/maintenance_service.py`
- `teleclaude/services/monitoring_service.py`
- `teleclaude/services/telegram.py`
- `teleclaude/services/whatsapp.py`
- `teleclaude/slug.py`
- `teleclaude/snippet_validation.py`
- `teleclaude/stt/backends/mlx_parakeet.py`
- `teleclaude/stt/backends/openai_whisper.py`
- `teleclaude/sync.py`
- `teleclaude/tagging/youtube.py`
- `teleclaude/tts/audio_focus.py`
- `teleclaude/tts/backends/elevenlabs.py`
- `teleclaude/tts/backends/macos_say.py`
- `teleclaude/tts/backends/mlx_tts.py`
- `teleclaude/tts/backends/openai_tts.py`
- `teleclaude/tts/backends/pyttsx3_tts.py`
- `teleclaude/tts/manager.py`
- `teleclaude/tts/models.py`
- `teleclaude/tts/queue_runner.py`
- `teleclaude/types/commands.py`
- `teleclaude/types/system.py`
- `teleclaude/types/todos.py`
- `teleclaude/utils/markdown.py`
- `teleclaude/utils/transcript_discovery.py`
- `teleclaude/utils/transcript/_block_renderers.py`
- `teleclaude/utils/transcript/_extraction.py`
- `teleclaude/utils/transcript/_iterators.py`
- `teleclaude/utils/transcript/_parsers.py`
- `teleclaude/utils/transcript/_rendering.py`
- `teleclaude/utils/transcript/_tool_calls.py`
- `teleclaude/utils/transcript/_utils.py`

## What

Write characterization tests for every source file listed above, following the
OBSERVE-ASSERT-VERIFY cycle. Each source file gets a corresponding test file
under `tests/unit/` mirroring the source directory structure.

## Acceptance criteria

- Every listed source file has a corresponding test file (or documented exemption)
- Tests pin actual behavior at public boundaries
- All tests pass on the current codebase
- No string assertions on human-facing text
- Max 5 mock patches per test
- Each test has a descriptive name that reads as a behavioral specification
- All existing tests still pass (no regressions)
- Lint and type checks pass

## Methodology: Characterization Testing (OBSERVE-ASSERT-VERIFY)

This is a **characterization testing** task, not TDD. The code already exists and works.
The goal is to pin current behavior as a safety net for future refactoring.

### Cycle per source file:

1. **OBSERVE** — Read the source file. Identify public functions/methods/classes that other
   modules call. Run representative inputs through the code mentally (or via quick test runs).
   Record actual return values, side effects, exceptions, and state changes.

2. **ASSERT** — Write tests that assert the observed behavior at public boundaries.
   The tests will pass immediately — this is expected and correct for characterization.
   Each test should have a descriptive name that serves as a behavioral specification.

3. **VERIFY** — For each test, mentally verify: if I introduced a deliberate fault in the
   production code (wrong return value, missing condition, swapped branch), would this test
   catch it? If not, the test is too shallow — strengthen or discard.

### Rules (from testing policy):

- Test at **public API boundaries only** — functions/methods other modules actually call
- **Behavioral contracts**, not implementation details — no mocking internals
- **No string assertions** on human-facing text (messages, CLI output, error prose)
- **Max 5 mock patches per test** — more indicates too many dependencies
- **One clear expectation per test**
- Mock at **architectural boundaries** (I/O, DB, network, external services)
- Every test must answer: **"What real bug in OUR code would this catch?"**
- Follow **1:1 source-to-test mapping**: `teleclaude/foo/bar.py` → `tests/unit/foo/test_bar.py`
- Use **pytest** with standard fixtures. Check existing `conftest.py` files for patterns.
- Skip files with genuinely no testable logic (pure re-exports, empty wrappers). Document why.

### Anti-patterns to avoid:

- Testing third-party library behavior (YAML round-trips, JSON serialization)
- Testing informational side-effects (log entries, metrics) unless the system depends on them
- Tautological assertions (asserting literals match their own source)
- Truthy-check assertions (`assert value` instead of asserting specific expected values)
- Over-mocking — if you need 6+ mocks, the code may need refactoring (document as tech debt)
