import pytest


def test_telec_keyboard_interrupt_exits_cleanly(monkeypatch):
    from teleclaude.cli import telec

    def _raise_interrupt() -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(telec, "_cleanup_stale_on_startup", _raise_interrupt)
    monkeypatch.setattr(telec.sys, "argv", ["telec"])

    with pytest.raises(SystemExit) as excinfo:
        telec.main()

    assert excinfo.value.code == 130
