# Implementation Plan: chartest-hooks

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [x] Characterize `teleclaude/hooks/api_routes.py` → `tests/unit/hooks/test_api_routes.py`
- [x] Characterize `teleclaude/hooks/checkpoint_flags.py` → `tests/unit/hooks/test_checkpoint_flags.py`
- [x] Characterize `teleclaude/hooks/config.py` → `tests/unit/hooks/test_config.py`
- [x] Characterize `teleclaude/hooks/delivery.py` → `tests/unit/hooks/test_delivery.py`
- [x] Characterize `teleclaude/hooks/dispatcher.py` → `tests/unit/hooks/test_dispatcher.py`
- [x] Characterize `teleclaude/hooks/handlers.py` → `tests/unit/hooks/test_handlers.py`
- [x] Characterize `teleclaude/hooks/inbound.py` → `tests/unit/hooks/test_inbound.py`
- [x] Characterize `teleclaude/hooks/matcher.py` → `tests/unit/hooks/test_matcher.py`
- [x] Characterize `teleclaude/hooks/registry.py` → `tests/unit/hooks/test_registry.py`
- [x] Characterize `teleclaude/hooks/webhook_models.py` → `tests/unit/hooks/test_webhook_models.py`
- [x] Characterize `teleclaude/hooks/whatsapp_handler.py` → `tests/unit/hooks/test_whatsapp_handler.py`
- [x] Characterize `teleclaude/hooks/adapters/base.py` → `tests/unit/hooks/adapters/test_base.py`
- [x] Characterize `teleclaude/hooks/adapters/claude.py` → `tests/unit/hooks/adapters/test_claude.py`
- [x] Characterize `teleclaude/hooks/adapters/codex.py` → `tests/unit/hooks/adapters/test_codex.py`
- [x] Characterize `teleclaude/hooks/adapters/gemini.py` → `tests/unit/hooks/adapters/test_gemini.py`
- [x] Characterize `teleclaude/hooks/checkpoint/_evidence.py` → `tests/unit/hooks/checkpoint/test__evidence.py`
- [x] Characterize `teleclaude/hooks/checkpoint/_git.py` → `tests/unit/hooks/checkpoint/test__git.py`
- [x] Characterize `teleclaude/hooks/checkpoint/_models.py` → `tests/unit/hooks/checkpoint/test__models.py`
- [x] Characterize `teleclaude/hooks/normalizers/github.py` → `tests/unit/hooks/normalizers/test_github.py`
- [x] Characterize `teleclaude/hooks/normalizers/whatsapp.py` → `tests/unit/hooks/normalizers/test_whatsapp.py`
- [x] Characterize `teleclaude/hooks/receiver/_session.py` → `tests/unit/hooks/receiver/test__session.py`
- [x] Characterize `teleclaude/hooks/utils/parse_helpers.py` → `tests/unit/hooks/utils/test_parse_helpers.py`
