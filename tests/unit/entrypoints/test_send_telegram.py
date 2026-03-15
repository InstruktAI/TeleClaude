"""Characterization tests for teleclaude.entrypoints.send_telegram."""

from __future__ import annotations

from typing import Any

import pytest

import teleclaude.entrypoints.send_telegram as send_telegram


def test_main_returns_two_when_token_env_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(send_telegram.DEFAULT_TOKEN_ENV, raising=False)
    monkeypatch.setenv(send_telegram.DEFAULT_USERNAME_ENV, "ops-team")

    assert send_telegram.main(["--text", "deploy failed"]) == 2


def test_main_returns_two_when_no_target_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(send_telegram.DEFAULT_TOKEN_ENV, "bot-token")
    monkeypatch.delenv(send_telegram.DEFAULT_USERNAME_ENV, raising=False)
    monkeypatch.delenv(send_telegram.DEFAULT_CHAT_ID_ENV, raising=False)

    assert send_telegram.main(["--text", "deploy failed"]) == 2


def test_main_sends_to_normalized_username_when_chat_id_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}  # guard: loose-dict - Test helper payloads intentionally vary by scenario.

    def fake_post_form(url: str, data: dict[str, str], timeout_s: float) -> send_telegram.ApiResponse:
        observed["url"] = url
        observed["data"] = data
        observed["timeout_s"] = timeout_s
        return {"ok": True}

    monkeypatch.setenv(send_telegram.DEFAULT_TOKEN_ENV, "secret-token")
    monkeypatch.setenv(send_telegram.DEFAULT_USERNAME_ENV, "OpsRoom")
    monkeypatch.delenv(send_telegram.DEFAULT_CHAT_ID_ENV, raising=False)
    monkeypatch.setattr(send_telegram, "_post_form", fake_post_form)

    assert send_telegram.main(["--text", "deploy succeeded", "--timeout", "3.5"]) == 0
    assert observed["url"] == "https://api.telegram.org/botsecret-token/sendMessage"
    assert observed["data"]["chat_id"] == "@OpsRoom"
    assert observed["data"]["disable_web_page_preview"] == "true"
    assert observed["timeout_s"] == 3.5


def test_main_prefers_explicit_chat_id_and_passes_parse_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, Any] = {}  # guard: loose-dict - Test helper payloads intentionally vary by scenario.

    def fake_post_form(url: str, data: dict[str, str], timeout_s: float) -> send_telegram.ApiResponse:
        observed["url"] = url
        observed["data"] = data
        observed["timeout_s"] = timeout_s
        return {"ok": True}

    monkeypatch.setenv(send_telegram.DEFAULT_TOKEN_ENV, "secret-token")
    monkeypatch.setenv(send_telegram.DEFAULT_USERNAME_ENV, "ops-room")
    monkeypatch.setenv(send_telegram.DEFAULT_CHAT_ID_ENV, "-10000")
    monkeypatch.setattr(send_telegram, "_post_form", fake_post_form)

    assert send_telegram.main(["--text", "alert", "--chat-id", "-20001", "--parse-mode", "HTML"]) == 0
    assert observed["data"]["chat_id"] == "-20001"
    assert observed["data"]["parse_mode"] == "HTML"


def test_main_returns_one_when_api_response_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(send_telegram.DEFAULT_TOKEN_ENV, "secret-token")
    monkeypatch.setenv(send_telegram.DEFAULT_CHAT_ID_ENV, "-10000")
    monkeypatch.setattr(send_telegram, "_post_form", lambda *_args, **_kwargs: {"ok": False, "description": "denied"})

    assert send_telegram.main(["--text", "alert"]) == 1
