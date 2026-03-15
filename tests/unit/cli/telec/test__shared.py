from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from teleclaude.cli.telec import _shared


def test_config_proxy_reads_runtime_config_attributes_lazily() -> None:
    fake_config_module = ModuleType("teleclaude.config")
    fake_config_module.config = SimpleNamespace(computer=SimpleNamespace(name="local"))

    with patch.dict(sys.modules, {"teleclaude.config": fake_config_module}):
        assert _shared.config.computer.name == "local"


def test_shared_constants_match_tmux_and_tui_contract() -> None:
    assert _shared.TMUX_ENV_KEY == "TMUX"
    assert _shared.TUI_ENV_KEY == "TELEC_TUI_SESSION"
    assert _shared.TUI_AUTH_EMAIL_ENV_KEY == "TELEC_AUTH_EMAIL"
    assert _shared.TUI_SESSION_NAME == "tc_tui"
