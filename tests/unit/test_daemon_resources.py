import types

import pytest

from teleclaude import daemon


def test_get_fd_count_returns_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon.os, "listdir", lambda _: ["1", "2", "3"])
    assert daemon._get_fd_count() == 3, "Expected fd count from listdir result"


def test_get_fd_count_handles_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_: str) -> list[str]:
        raise OSError("boom")

    monkeypatch.setattr(daemon.os, "listdir", _raise)
    assert daemon._get_fd_count() is None, "Expected None when listdir fails"


def test_get_rss_kb_linux_units(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(ru_maxrss=2048)
    monkeypatch.setattr(daemon.resource, "getrusage", lambda _: usage)
    monkeypatch.setattr(daemon.sys, "platform", "linux")
    assert daemon._get_rss_kb() == 2048, "Expected ru_maxrss passthrough on non-darwin"


def test_get_rss_kb_darwin_units(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(ru_maxrss=2048)
    monkeypatch.setattr(daemon.resource, "getrusage", lambda _: usage)
    monkeypatch.setattr(daemon.sys, "platform", "darwin")
    assert daemon._get_rss_kb() == 2, "Expected ru_maxrss bytes to KB conversion on darwin"
