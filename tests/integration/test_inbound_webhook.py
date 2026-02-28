"""Integration tests for inbound webhook endpoint flow."""

import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import teleclaude.config as config_module
import teleclaude.daemon as daemon_module
from teleclaude.api_server import APIServer
from teleclaude.daemon import TeleClaudeDaemon as Daemon


def _write_project_config(project_root: Path, webhook_event_type: str) -> None:
    project_root.joinpath("config.yml").write_text("{}", encoding="utf-8")
    project_config = {
        "hooks": {
            "inbound": {"github": {"secret": "webhook-secret"}},
            "subscriptions": [
                {
                    "id": "github-push",
                    "contract": {"source": {"match": "github"}, "type": {"match": webhook_event_type}},
                    "target": {"url": "https://example.com/webhook", "secret": "dispatch-secret"},
                }
            ],
        }
    }
    project_root.joinpath("teleclaude.yml").write_text(yaml.safe_dump(project_config), encoding="utf-8")


def _build_signature(secret: str, payload: bytes) -> str:
    return f"sha256={hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()}"


def _init_inbound_app(
    daemon: Daemon,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_enqueuer: AsyncMock | None = None,
) -> FastAPI:
    config_dir_file = project_root / "config.yml"
    monkeypatch.setattr(daemon_module, "config_path", config_dir_file)
    monkeypatch.setattr(config_module, "config_path", config_dir_file)
    if patch_enqueuer is not None:
        from teleclaude.core import db as db_module

        monkeypatch.setattr(db_module.db, "enqueue_webhook", patch_enqueuer)

    daemon.lifecycle.api_server = APIServer(
        client=daemon.client,
        cache=daemon.cache,
        task_registry=daemon.task_registry,
    )
    return daemon.lifecycle.api_server.app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_webhook_dispatches_to_contract(monkeypatch, tmp_path, daemon_with_mocked_telegram):
    daemon = daemon_with_mocked_telegram
    _write_project_config(tmp_path, webhook_event_type="push")
    enqueue_webhook = AsyncMock()
    app = _init_inbound_app(daemon, tmp_path, monkeypatch=monkeypatch, patch_enqueuer=enqueue_webhook)
    await daemon._init_webhook_service()

    client = TestClient(app)
    payload = {"ref": "refs/heads/main", "repository": {"full_name": "acme/widget"}, "sender": {"login": "octocat"}}
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/hooks/inbound/github",
        content=body,
        headers={"X-Hub-Signature-256": _build_signature("webhook-secret", body), "X-GitHub-Event": "push"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    enqueue_webhook.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_webhook_missing_signature_rejected(monkeypatch, tmp_path, daemon_with_mocked_telegram):
    daemon = daemon_with_mocked_telegram
    _write_project_config(tmp_path, webhook_event_type="push")
    app = _init_inbound_app(daemon, tmp_path, monkeypatch=monkeypatch)
    await daemon._init_webhook_service()

    body = b'{"repo":"acme/widget"}'
    client = TestClient(app)

    response = client.post("/hooks/inbound/github", content=body)
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_webhook_invalid_signature_rejected(monkeypatch, tmp_path, daemon_with_mocked_telegram):
    daemon = daemon_with_mocked_telegram
    _write_project_config(tmp_path, webhook_event_type="push")
    app = _init_inbound_app(daemon, tmp_path, monkeypatch=monkeypatch)
    await daemon._init_webhook_service()

    body = b'{"repo":"acme/widget"}'
    client = TestClient(app)

    response = client.post(
        "/hooks/inbound/github",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_webhook_invalid_json_rejected(monkeypatch, tmp_path, daemon_with_mocked_telegram):
    daemon = daemon_with_mocked_telegram
    _write_project_config(tmp_path, webhook_event_type="push")
    app = _init_inbound_app(daemon, tmp_path, monkeypatch=monkeypatch)
    await daemon._init_webhook_service()

    body = b"{not-json"
    client = TestClient(app)

    response = client.post(
        "/hooks/inbound/github",
        content=body,
        headers={"X-Hub-Signature-256": _build_signature("webhook-secret", body)},
    )
    assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_webhook_normalizer_exception_returns_400(monkeypatch, tmp_path, daemon_with_mocked_telegram):
    daemon = daemon_with_mocked_telegram
    _write_project_config(tmp_path, webhook_event_type="push")
    app = _init_inbound_app(daemon, tmp_path, monkeypatch=monkeypatch)
    await daemon._init_webhook_service()

    body = b'["not", "a", "dict"]'
    client = TestClient(app)

    response = client.post(
        "/hooks/inbound/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _build_signature("webhook-secret", body),
            "X-GitHub-Event": "push",
        },
    )
    assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inbound_webhook_dispatch_failure_returns_502(tmp_path, monkeypatch, daemon_with_mocked_telegram):
    async def failing_dispatch(self: object, _event: object) -> None:
        raise RuntimeError("dispatch failed")

    daemon = daemon_with_mocked_telegram
    _write_project_config(tmp_path, webhook_event_type="push")
    app = _init_inbound_app(daemon, tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr("teleclaude.hooks.dispatcher.HookDispatcher.dispatch", failing_dispatch)
    await daemon._init_webhook_service()

    body = b'{"ref":"refs/heads/main","repository":{"full_name":"acme/widget"}}'
    client = TestClient(app)

    response = client.post(
        "/hooks/inbound/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _build_signature("webhook-secret", body),
            "X-GitHub-Event": "push",
        },
    )
    assert response.status_code == 502
