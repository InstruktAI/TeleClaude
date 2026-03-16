# Requirements: fix-pane-layout-grid-guard-2

## Context

Inline work submitted for review via `telec todo from-main`.

## Changes

```
 agents/commands/next-review-build.md               |   6 +
 docs/global/index.yaml                             |   4 +-
 .../procedure/lifecycle/work/review.md             |  11 +-
 teleclaude/cli/tui/pane_layout.py                  |   6 +-
 teleclaude/install/wrappers/git                    |   3 +
 tests/unit/cli/tui/test_animation_engine.py        |  13 +-
 tests/unit/cli/tui/test_messages.py                |  40 --
 tests/unit/cli/tui/test_pane_layout.py             |  10 +
 tests/unit/cli/tui/test_todos.py                   |  30 -
 tests/unit/cli/tui/views/test__config_constants.py |  12 -
 tests/unit/core/adapter_client/test__client.py     |  20 -
 tests/unit/core/models/test__adapter.py            | 112 ---
 tests/unit/core/models/test__context.py            |  94 ---
 tests/unit/core/models/test__session.py            |  97 ---
 tests/unit/core/models/test__snapshot.py           |  60 --
 tests/unit/core/test_cache.py                      |   5 -
 tests/unit/core/test_codex_prompt_submit.py        |  11 -
 tests/unit/core/test_command_mapper.py             |  15 +-
 tests/unit/core/test_inbound_errors.py             |  44 --
 tests/unit/core/test_voice_assignment.py           |  54 --
 tests/unit/events/schemas/test_content.py          |  46 +-
 .../events/schemas/test_creative_production.py     |  50 --
 .../unit/events/schemas/test_customer_relations.py |  50 --
 tests/unit/events/schemas/test_deployment.py       |  45 --
 tests/unit/events/schemas/test_marketing.py        |  53 --
 tests/unit/events/schemas/test_node.py             |  44 --
 tests/unit/events/schemas/test_notification.py     |  40 --
 tests/unit/events/schemas/test_schema.py           |  32 -
 tests/unit/events/schemas/test_signal.py           |  43 --
 .../events/schemas/test_software_development.py    |  74 --
 tests/unit/events/schemas/test_system.py           |  60 --
 tests/unit/helpers/youtube_helper/test__parsers.py |  21 +-
 tests/unit/hooks/checkpoint/test__models.py        |  41 --
 .../test_conversation_projector.py                 |   2 +-
 tests/unit/stt/backends/test_openai_whisper.py     |   5 +-
 tests/unit/test_api_models.py                      | 747 +--------------------
 tests/unit/test_content_scaffold.py                |   5 +-
 tests/unit/tts/test_models.py                      |  41 --
 tests/unit/types/test_commands.py                  |  17 -
 tests/unit/types/test_system.py                    |  33 -
 tests/unit/types/test_todos.py                     |  58 +-
 41 files changed, 77 insertions(+), 2077 deletions(-)
```

## Description

See diff for details.

## Acceptance criteria

- Changes are correct and complete
- Tests cover new/changed behavior
- Code quality meets project standards
