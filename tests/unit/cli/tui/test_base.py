from __future__ import annotations

import pytest

from teleclaude.cli.tui.base import TelecMixin


class _DummyTelecWidget(TelecMixin):
    pass


@pytest.mark.unit
def test_telec_mixin_disables_auto_links() -> None:
    assert _DummyTelecWidget.auto_links is False
