"""Unit tests for GitHub inbound normalizer."""

from __future__ import annotations

from teleclaude.hooks.normalizers.github import normalize_github


def test_normalize_github_push_event() -> None:
    payload = {
        "ref": "refs/heads/main",
        "action": "opened",
        "repository": {"full_name": "acme/widget"},
        "sender": {"login": "octocat"},
    }
    event = normalize_github(payload, {"x-github-event": "push"})

    assert event.source == "github"
    assert event.type == "push"
    assert event.properties["repo"] == "acme/widget"
    assert event.properties["sender"] == "octocat"
    assert event.properties["action"] == "opened"
    assert event.properties["ref"] == "refs/heads/main"
    assert event.payload == payload


def test_normalize_github_ping_event() -> None:
    payload = {
        "zen": "Welcome to the webhook world!",
        "hook_id": 1234,
        "repository": {"full_name": "acme/widget"},
        "sender": {"login": "github"},
    }
    event = normalize_github(payload, {"x-github-event": "ping"})

    assert event.type == "ping"
    assert event.properties["zen"] == "Welcome to the webhook world!"
    assert event.properties["hook_id"] == 1234


def test_normalize_github_pull_request_event() -> None:
    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/widget"},
        "sender": {"login": "octocat"},
    }
    event = normalize_github(payload, {"x-github-event": "pull_request"})

    assert event.type == "pull_request"
    assert event.properties["action"] == "opened"


def test_normalize_github_missing_header_falls_back_to_unknown() -> None:
    payload = {"repository": {"full_name": "acme/widget"}, "sender": {"login": "octocat"}}
    event = normalize_github(payload, {})

    assert event.type == "unknown"
    assert event.properties["repo"] == "acme/widget"
    assert event.properties["sender"] == "octocat"


def test_normalize_github_minimal_payload_is_safe() -> None:
    event = normalize_github({}, {})

    assert event.type == "unknown"
    assert event.payload == {}
