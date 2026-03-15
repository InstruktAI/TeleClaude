"""Characterization tests for teleclaude/cli/models.py."""

from __future__ import annotations

from teleclaude.cli.models import (
    SubscribeData,
    SubscribeRequest,
    UnsubscribeData,
    UnsubscribeRequest,
)

# ---------------------------------------------------------------------------
# SubscribeData
# ---------------------------------------------------------------------------


def test_subscribe_data_stores_computer_and_types() -> None:
    data = SubscribeData(computer="local", types=["sessions", "preparation"])
    assert data.computer == "local"
    assert data.types == ["sessions", "preparation"]


def test_subscribe_data_empty_types() -> None:
    data = SubscribeData(computer="remote", types=[])
    assert data.types == []


# ---------------------------------------------------------------------------
# UnsubscribeData
# ---------------------------------------------------------------------------


def test_unsubscribe_data_stores_computer() -> None:
    data = UnsubscribeData(computer="local")
    assert data.computer == "local"


# ---------------------------------------------------------------------------
# SubscribeRequest
# ---------------------------------------------------------------------------


def test_subscribe_request_wraps_subscribe_data() -> None:
    inner = SubscribeData(computer="local", types=["sessions"])
    req = SubscribeRequest(subscribe=inner)
    assert req.subscribe is inner
    assert req.subscribe.computer == "local"
    assert req.subscribe.types == ["sessions"]


# ---------------------------------------------------------------------------
# UnsubscribeRequest
# ---------------------------------------------------------------------------


def test_unsubscribe_request_wraps_unsubscribe_data() -> None:
    inner = UnsubscribeData(computer="local")
    req = UnsubscribeRequest(unsubscribe=inner)
    assert req.unsubscribe is inner
    assert req.unsubscribe.computer == "local"
