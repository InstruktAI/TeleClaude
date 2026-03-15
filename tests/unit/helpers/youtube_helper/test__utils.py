"""Characterization tests for teleclaude.helpers.youtube_helper._utils."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from teleclaude.helpers.youtube import refresh_cookies as refresh_module
from teleclaude.helpers.youtube_helper import _utils
from teleclaude.helpers.youtube_helper._models import YouTubeBackoffError

pytestmark = pytest.mark.unit


class TestSafeGetHelpers:
    def test_safe_get_variants_fall_back_for_wrong_shapes(self) -> None:
        payload = {"items": [{"name": "first"}]}

        assert _utils._safe_get(payload, "items", 0, "name") == "first"
        assert _utils._safe_get(payload, "items", "wrong", default="fallback") == "fallback"
        assert _utils._safe_get_dict(payload, "items", 0) == {"name": "first"}
        assert _utils._safe_get_list(payload, "items", 0) == []
        assert _utils._safe_get_str(payload, "items", 0, "missing", default="fallback") == "fallback"


class TestBackoff:
    def test_check_backoff_raises_for_active_window(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        backoff_file = tmp_path / ".backoff"
        backoff_file.write_text((datetime.now(UTC) + timedelta(seconds=30)).isoformat(), encoding="utf-8")
        monkeypatch.setattr(_utils, "BACKOFF_FILE", backoff_file)

        with pytest.raises(YouTubeBackoffError, match="backoff active"):
            _utils._check_backoff()

    def test_check_backoff_removes_invalid_timestamp(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        backoff_file = tmp_path / ".backoff"
        backoff_file.write_text("not-an-iso-date", encoding="utf-8")
        monkeypatch.setattr(_utils, "BACKOFF_FILE", backoff_file)

        _utils._check_backoff()

        assert backoff_file.exists() is False


class TestBuildInnertubeHeaders:
    def test_includes_sapisid_authorization_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_utils, "_load_cookies_txt", lambda path: {"SAPISID": "secret", "SID": "sid"})
        monkeypatch.setattr(_utils.time, "time", lambda: 123)

        headers, cookies_file = _utils._build_innertube_headers("/tmp/cookies.txt")

        assert cookies_file == "/tmp/cookies.txt"
        assert headers["Cookie"] == "SAPISID=secret; SID=sid"
        assert headers["Authorization"].startswith("SAPISIDHASH 123_")


class TestRefreshCookiesIfNeeded:
    def test_returns_false_during_refresh_cooldown(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(_utils.Path, "home", classmethod(lambda cls: tmp_path))
        profile_dir = tmp_path / ".config" / "youtube" / "playwright-profile"
        profile_dir.mkdir(parents=True)
        lock_path = tmp_path / ".config" / "youtube" / ".refresh_lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("", encoding="utf-8")
        monkeypatch.setattr(_utils, "_COOKIE_REFRESH_LOCK", lock_path)

        assert _utils._refresh_cookies_if_needed() is False

    def test_calls_refresh_script_when_profile_exists(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(_utils.Path, "home", classmethod(lambda cls: tmp_path))
        profile_dir = tmp_path / ".config" / "youtube" / "playwright-profile"
        profile_dir.mkdir(parents=True)
        lock_path = tmp_path / ".config" / "youtube" / ".refresh_lock"
        monkeypatch.setattr(_utils, "_COOKIE_REFRESH_LOCK", lock_path)
        monkeypatch.setattr(
            refresh_module,
            "refresh_cookies",
            lambda profile_dir, output_path, headless: (
                profile_dir == tmp_path / ".config" / "youtube" / "playwright-profile"
                and output_path == tmp_path / ".config" / "youtube" / "cookies.txt"
                and headless is True
            ),
        )

        assert _utils._refresh_cookies_if_needed() is True
        assert lock_path.exists() is True
