import types

import pytest

from teleclaude.services import monitoring_service


def test_get_fd_count_returns_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitoring_service.os, "listdir", lambda _: ["1", "2", "3"])
    assert monitoring_service._get_fd_count() == 3, "Expected fd count from listdir result"


def test_get_fd_count_handles_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_: str) -> list[str]:
        raise OSError("boom")

    monkeypatch.setattr(monitoring_service.os, "listdir", _raise)
    assert monitoring_service._get_fd_count() is None, "Expected None when listdir fails"


def test_get_rss_kb_linux_units(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(ru_maxrss=2048)
    monkeypatch.setattr(monitoring_service.resource, "getrusage", lambda _: usage)
    monkeypatch.setattr(monitoring_service.platform, "system", lambda: "Linux")
    assert monitoring_service._get_rss_kb() == 2048, "Expected ru_maxrss passthrough on non-darwin"


def test_get_rss_kb_darwin_units(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(ru_maxrss=2048)
    monkeypatch.setattr(monitoring_service.resource, "getrusage", lambda _: usage)
    monkeypatch.setattr(monitoring_service.platform, "system", lambda: "Darwin")
    assert monitoring_service._get_rss_kb() == 2, "Expected ru_maxrss bytes to KB conversion on darwin"
