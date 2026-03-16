# Requirements: fix-ci-release-credentials-3

## Context
Inline work submitted for review via `telec todo from-main`.

## Changes
```
 .github/workflows/release.yaml                     |  2 +-
 bin/setup-runner.sh                                | 98 ++++++++++++++++++++++
 jobs/dependency_upgrade.py                         |  2 +-
 teleclaude/cli/tui/pane_layout.py                  |  2 +-
 teleclaude/install/wrappers/git                    |  2 +-
 teleclaude/todo_scaffold.py                        | 20 +++--
 tests/unit/cli/tui/test_animation_engine.py        |  2 +-
 tests/unit/cli/tui/test_messages.py                | 40 ---------
 tests/unit/cli/tui/test_pane_layout.py             |  2 +-
 tests/unit/cli/tui/test_todos.py                   |  2 +-
 tests/unit/cli/tui/views/test__config_constants.py |  2 +-
 tests/unit/core/adapter_client/test__client.py     |  2 +-
 tests/unit/core/models/test__adapter.py            |  2 +-
 tests/unit/core/models/test__context.py            | 94 ---------------------
 tests/unit/core/models/test__session.py            |  2 +-
 tests/unit/core/models/test__snapshot.py           |  2 +-
 tests/unit/core/operations/test_service.py         |  2 +-
 tests/unit/core/test_cache.py                      |  2 +-
 tests/unit/core/test_codex_prompt_submit.py        |  2 +-
 tests/unit/core/test_command_mapper.py             |  2 +-
 tests/unit/core/test_inbound_errors.py             | 44 ----------
 tests/unit/core/test_voice_assignment.py           | 54 ------------
 tests/unit/events/schemas/test_content.py          |  2 +-
 .../events/schemas/test_creative_production.py     |  2 +-
 .../unit/events/schemas/test_customer_relations.py |  2 +-
 tests/unit/events/schemas/test_deployment.py       |  2 +-
 tests/unit/events/schemas/test_marketing.py        |  2 +-
 tests/unit/events/schemas/test_node.py             |  2 +-
 tests/unit/events/schemas/test_notification.py     |  2 +-
 tests/unit/events/schemas/test_schema.py           |  2 +-
 tests/unit/events/schemas/test_signal.py           |  2 +-
 .../events/schemas/test_software_development.py    |  2 +-
 tests/unit/events/schemas/test_system.py           |  2 +-
 tests/unit/helpers/youtube_helper/test__parsers.py |  2 +-
 tests/unit/hooks/checkpoint/test__models.py        | 41 ---------
 .../test_conversation_projector.py                 |  2 +-
 tests/unit/stt/backends/test_openai_whisper.py     |  2 +-
 tests/unit/test_api_models.py                      |  2 +-
 tests/unit/test_content_scaffold.py                |  2 +-
 tests/unit/tts/test_models.py                      | 41 ---------
 tests/unit/types/test_commands.py                  |  2 +-
 tests/unit/types/test_system.py                    | 33 --------
 tests/unit/types/test_todos.py                     |  2 +-
 todos/fix-pane-layout-grid-guard-2/demo.md         | 12 ---
 .../implementation-plan.md                         |  5 --
 todos/fix-pane-layout-grid-guard-2/input.md        |  3 -
 .../quality-checklist.md                           | 41 ---------
 todos/fix-pane-layout-grid-guard-2/requirements.md | 62 --------------
 todos/fix-pane-layout-grid-guard-2/state.yaml      | 22 -----
 todos/fix-pane-layout-grid-guard/demo.md           | 12 ---
 .../implementation-plan.md                         |  5 --
 todos/fix-pane-layout-grid-guard/input.md          |  3 -
 .../quality-checklist.md                           | 41 ---------
 todos/fix-pane-layout-grid-guard/requirements.md   | 62 --------------
 todos/fix-pane-layout-grid-guard/state.yaml        | 22 -----
 55 files changed, 145 insertions(+), 678 deletions(-)
```

## Description
Check Claude credentials via Keychain instead of Desktop app config; add runner setup script

## Acceptance criteria
- Changes are correct and complete
- Tests cover new/changed behavior
- Code quality meets project standards
