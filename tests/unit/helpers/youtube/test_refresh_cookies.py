"""Characterization tests for teleclaude.helpers.youtube.refresh_cookies."""

from __future__ import annotations

import sys
import types
from collections.abc import Mapping
from pathlib import Path

import pytest

from teleclaude.helpers.youtube import refresh_cookies

pytestmark = pytest.mark.unit


class _FakePage:
    def __init__(self, goto_error: Exception | None = None) -> None:
        self.goto_error = goto_error
        self.waited = 0
        self.goto_calls: list[tuple[str, int | None, str | None]] = []

    def goto(self, url: str, timeout: int | None = None, wait_until: str | None = None) -> None:
        self.goto_calls.append((url, timeout, wait_until))
        if self.goto_error is not None:
            raise self.goto_error

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waited = milliseconds


class _FakeContext:
    def __init__(self, cookies: list[Mapping[str, object]], goto_error: Exception | None = None) -> None:
        self._cookies = cookies
        self.page = _FakePage(goto_error=goto_error)
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page

    def cookies(self, urls: list[str]) -> list[Mapping[str, object]]:
        return list(self._cookies)

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context

    def launch_persistent_context(self, **kwargs: object) -> _FakeContext:
        return self.context


class _FakePlaywrightContextManager:
    def __init__(self, context: _FakeContext) -> None:
        self.chromium = _FakeChromium(context)

    def __enter__(self) -> _FakePlaywrightContextManager:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        return None


def _install_fake_playwright(monkeypatch: pytest.MonkeyPatch, context: _FakeContext) -> None:
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _FakePlaywrightContextManager(context)
    playwright = types.ModuleType("playwright")
    playwright.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


class TestCookiesToNetscape:
    def test_filters_non_youtube_domains_and_normalizes_fields(self) -> None:
        text = refresh_cookies.cookies_to_netscape(
            [
                {"domain": ".youtube.com", "name": "SID", "value": "abc", "secure": True, "expires": 42, "path": "/"},
                {"domain": ".google.com", "name": 1, "value": 2, "path": 3},
                {"domain": ".example.com", "name": "ignored", "value": "ignored"},
            ]
        )

        assert ".youtube.com\tTRUE\t/\tTRUE\t42\tSID\tabc" in text
        assert ".google.com\tTRUE\t/\tFALSE" in text
        assert "example.com" not in text


class TestRefreshCookies:
    def test_returns_false_when_profile_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _install_fake_playwright(monkeypatch, _FakeContext([]))

        success = refresh_cookies.refresh_cookies(
            profile_dir=tmp_path / "missing-profile",
            output_path=tmp_path / "cookies.txt",
        )

        captured = capsys.readouterr()
        assert success is False
        assert "Run with --setup first" in captured.err

    def test_writes_filtered_cookie_file_when_auth_cookies_exist(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        profile_dir = tmp_path / "profile"
        output_path = tmp_path / "cookies.txt"
        profile_dir.mkdir()
        context = _FakeContext(
            [
                {"domain": ".youtube.com", "name": "SID", "value": "sid"},
                {"domain": ".youtube.com", "name": "HSID", "value": "hsid"},
                {"domain": ".youtube.com", "name": "SSID", "value": "ssid"},
                {"domain": ".google.com", "name": "APISID", "value": "apisid"},
                {"domain": ".google.com", "name": "SAPISID", "value": "sapisid"},
                {"domain": ".example.com", "name": "skip", "value": "skip"},
            ]
        )
        _install_fake_playwright(monkeypatch, context)

        success = refresh_cookies.refresh_cookies(
            profile_dir=profile_dir,
            output_path=output_path,
            headless=True,
            timeout=1234,
        )

        assert success is True
        assert output_path.exists()
        assert ".youtube.com" in output_path.read_text(encoding="utf-8")
        assert ".example.com" not in output_path.read_text(encoding="utf-8")
        assert context.page.goto_calls == [("https://www.youtube.com", 1234, "networkidle")]
        assert context.page.waited == 2000
        assert context.closed is True


class TestMain:
    def test_setup_mode_exits_with_success_code(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(sys, "argv", ["refresh_cookies.py", "--setup", "--profile", str(tmp_path / "profile")])
        monkeypatch.setattr(refresh_cookies, "setup_profile", lambda profile_dir: True)

        with pytest.raises(SystemExit) as exc_info:
            refresh_cookies.main()

        assert exc_info.value.code == 0
