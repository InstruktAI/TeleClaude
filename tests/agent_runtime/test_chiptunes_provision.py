from __future__ import annotations

import asyncio
import builtins
import hashlib
import shutil
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import py7zr
import pytest

from teleclaude import daemon as daemon_mod
from teleclaude.chiptunes import manager as manager_mod
from teleclaude.chiptunes import provision as provision_mod
from teleclaude.chiptunes.manager import CHIPTUNES_PROVISION_FAILED_EVENT, ChiptunesManager
from teleclaude.chiptunes.provision import (
    PROVISION_INSTALLED,
    PROVISION_SKIPPED,
    ChiptunesChecksumError,
    ChiptunesExtractorUnavailable,
    ChiptunesProvisionError,
    provision_hvsc_corpus,
)
from teleclaude.config import ChiptunesConfig
from teleclaude.daemon import TeleClaudeDaemon
from teleclaude.services.process_janitor.registry import RegistryResolution

pytestmark = pytest.mark.functional

ARCHIVE_URL = "https://example.test/hvsc.7z"
TEST_SID_NAME = "test.sid"
EXISTING_BYTES = b"existing\n"
SID_BYTES = b"sid fixture\n"


class _NoopRegistry:
    def resolve_chiptunes(self, *, live_pids: list[int], socket_reachable: bool) -> RegistryResolution:
        del live_pids, socket_reachable
        return RegistryResolution(adopted_pid=None, stale_pid=None)

    def register_chiptunes(self, pid: int, *, lease_ttl_seconds: int) -> None:
        del pid, lease_ttl_seconds

    def clear_chiptunes(self) -> None:
        return


class _WarningSpy:
    def __init__(self) -> None:
        self.events: list[str] = []

    def warning(self, event: str, **_fields: object) -> None:
        self.events.append(event)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(path: Path, *, archive_path: Path, sha256: str | None = None) -> None:
    path.write_text(
        (
            "{\n"
            '  "version": 84,\n'
            f'  "archive_url": "{ARCHIVE_URL}",\n'
            f'  "sha256": "{sha256 or _sha256(archive_path)}"\n'
            "}\n"
        ),
        encoding="utf-8",
    )


def _create_archive(tmp_path: Path) -> Path:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    sid_file = source_dir / TEST_SID_NAME
    sid_file.write_bytes(SID_BYTES)
    archive_path = tmp_path / "fixture.7z"
    with py7zr.SevenZipFile(archive_path, mode="w") as archive:
        archive.write(sid_file, arcname=TEST_SID_NAME)
    return archive_path


def _patch_download(monkeypatch: pytest.MonkeyPatch, archive_path: Path) -> list[str]:
    downloaded_urls: list[str] = []

    def download(url: str, target: Path) -> None:
        downloaded_urls.append(url)
        shutil.copyfile(archive_path, target)

    monkeypatch.setattr(provision_mod, "_download_archive", download)
    return downloaded_urls


def test_populated_music_dir_skips_without_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / TEST_SID_NAME).write_bytes(EXISTING_BYTES)
    manifest_path = tmp_path / "manifest.json"
    archive_path = _create_archive(tmp_path)
    _write_manifest(manifest_path, archive_path=archive_path)
    downloaded_urls = _patch_download(monkeypatch, archive_path)

    result = provision_hvsc_corpus(music_dir, manifest_path=manifest_path)

    assert result.status == PROVISION_SKIPPED
    assert downloaded_urls == []
    assert (music_dir / TEST_SID_NAME).read_bytes() == EXISTING_BYTES


def test_checksum_mismatch_refuses_install_and_leaves_music_dir_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    music_dir = tmp_path / "music"
    manifest_path = tmp_path / "manifest.json"
    archive_path = _create_archive(tmp_path)
    _write_manifest(manifest_path, archive_path=archive_path, sha256="0" * 64)
    _patch_download(monkeypatch, archive_path)

    with pytest.raises(ChiptunesChecksumError):
        provision_hvsc_corpus(music_dir, manifest_path=manifest_path)

    assert not music_dir.exists()


def test_unreachable_archive_raises_provision_error_and_leaves_music_dir_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    music_dir = tmp_path / "music"
    manifest_path = tmp_path / "manifest.json"
    archive_path = _create_archive(tmp_path)
    _write_manifest(manifest_path, archive_path=archive_path)

    def fail_download(url: str, target: Path) -> None:
        del url, target
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(provision_mod, "_download_archive", fail_download)

    with pytest.raises(ChiptunesProvisionError):
        provision_hvsc_corpus(music_dir, manifest_path=manifest_path)

    assert not music_dir.exists()


def test_matching_archive_extracts_into_music_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    manifest_path = tmp_path / "manifest.json"
    archive_path = _create_archive(tmp_path)
    _write_manifest(manifest_path, archive_path=archive_path)
    downloaded_urls = _patch_download(monkeypatch, archive_path)

    result = provision_hvsc_corpus(music_dir, manifest_path=manifest_path)

    assert result.status == PROVISION_INSTALLED
    assert downloaded_urls == [ARCHIVE_URL]
    assert (music_dir / TEST_SID_NAME).read_bytes() == SID_BYTES


def test_missing_py7zr_raises_actionable_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive_path = _create_archive(tmp_path)
    original_import = builtins.__import__

    def import_without_py7zr(name: str, *args: object, **kwargs: object) -> object:
        if name == "py7zr":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_py7zr)

    with pytest.raises(ChiptunesExtractorUnavailable):
        provision_mod._extract_archive(archive_path, tmp_path / "music")


@pytest.mark.asyncio
async def test_manager_reload_provisions_absent_enabled_corpus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    manager = ChiptunesManager(music_dir, registry=_NoopRegistry())
    monkeypatch.setattr(
        manager_mod,
        "_current_chiptunes_config",
        lambda: ChiptunesConfig(enabled=True, music_dir=str(music_dir), volume=0.5),
    )

    async def provision(path: Path) -> None:
        path.mkdir(parents=True)
        (path / TEST_SID_NAME).write_bytes(SID_BYTES)

    monkeypatch.setattr(manager_mod, "provision_hvsc_corpus_async", provision)

    task = manager.reload()
    assert task is not None
    await task

    assert manager.enabled is True
    assert (music_dir / TEST_SID_NAME).read_bytes() == SID_BYTES


@pytest.mark.asyncio
async def test_manager_reload_logs_and_stays_disabled_when_provisioning_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    music_dir = tmp_path / "music"
    manager = ChiptunesManager(music_dir, registry=_NoopRegistry())
    warning_spy = _WarningSpy()
    monkeypatch.setattr(manager_mod, "logger", warning_spy)
    monkeypatch.setattr(
        manager_mod,
        "_current_chiptunes_config",
        lambda: ChiptunesConfig(enabled=True, music_dir=str(music_dir), volume=0.5),
    )

    async def fail_provision(_path: Path) -> None:
        raise ChiptunesProvisionError

    monkeypatch.setattr(manager_mod, "provision_hvsc_corpus_async", fail_provision)

    task = manager.reload()
    assert task is not None
    await task

    assert manager.enabled is False
    assert not music_dir.exists()
    assert warning_spy.events == [CHIPTUNES_PROVISION_FAILED_EVENT]


def test_manager_reload_disables_without_touching_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / TEST_SID_NAME).write_bytes(EXISTING_BYTES)
    manager = ChiptunesManager(music_dir, registry=_NoopRegistry())
    manager._enabled = True
    monkeypatch.setattr(
        manager_mod,
        "_current_chiptunes_config",
        lambda: ChiptunesConfig(enabled=False, music_dir=str(music_dir), volume=0.5),
    )
    monkeypatch.setattr(manager, "_send_cmd", lambda _cmd: None)
    monkeypatch.setattr(manager, "_disconnect", lambda: None)
    monkeypatch.setattr(manager, "_kill_worker", lambda: None)

    task = manager.reload()

    assert task is None
    assert manager.enabled is False
    assert (music_dir / TEST_SID_NAME).read_bytes() == EXISTING_BYTES


def test_manager_reload_activates_populated_enabled_corpus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / TEST_SID_NAME).write_bytes(EXISTING_BYTES)
    manager = ChiptunesManager(music_dir, registry=_NoopRegistry())
    monkeypatch.setattr(
        manager_mod,
        "_current_chiptunes_config",
        lambda: ChiptunesConfig(enabled=True, music_dir=str(music_dir), volume=0.5),
    )

    async def fail_provision(_path: Path) -> None:
        raise AssertionError("populated corpus should not provision")

    monkeypatch.setattr(manager_mod, "provision_hvsc_corpus_async", fail_provision)

    task = manager.reload()

    assert task is None
    assert manager.enabled is True


@pytest.mark.asyncio
async def test_daemon_config_reload_applies_chiptunes_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / TEST_SID_NAME).write_bytes(EXISTING_BYTES)
    manager = ChiptunesManager(music_dir, registry=_NoopRegistry())
    monkeypatch.setattr(daemon_mod, "reload_config", lambda: ["chiptunes"])
    monkeypatch.setattr(daemon_mod, "restart_required_sections", lambda _changed: [])
    monkeypatch.setattr(
        manager_mod,
        "_current_chiptunes_config",
        lambda: ChiptunesConfig(enabled=True, music_dir=str(music_dir), volume=0.5),
    )
    daemon = SimpleNamespace(
        tts_manager=SimpleNamespace(reload=lambda: None),
        chiptunes_manager=manager,
        request_shutdown=lambda _reason: None,
    )

    await TeleClaudeDaemon._on_config_files_changed(daemon)

    assert manager.enabled is True


def test_daemon_startup_gate_off_schedules_no_provision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    manager = ChiptunesManager(music_dir, registry=_NoopRegistry())
    monkeypatch.setattr(
        manager_mod,
        "_current_chiptunes_config",
        lambda: ChiptunesConfig(enabled=False, music_dir=str(music_dir), volume=0.5),
    )
    monkeypatch.setattr(manager, "_send_cmd", lambda _cmd: None)
    monkeypatch.setattr(manager, "_disconnect", lambda: None)
    monkeypatch.setattr(manager, "_kill_worker", lambda: None)
    daemon = SimpleNamespace(chiptunes_manager=manager)

    TeleClaudeDaemon._apply_chiptunes_startup_state(daemon)

    assert manager.enabled is False
    assert not music_dir.exists()


@pytest.mark.asyncio
async def test_daemon_startup_gate_on_schedules_self_heal_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    music_dir = tmp_path / "music"
    manager = ChiptunesManager(music_dir, registry=_NoopRegistry())
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[Path] = []
    monkeypatch.setattr(
        manager_mod,
        "_current_chiptunes_config",
        lambda: ChiptunesConfig(enabled=True, music_dir=str(music_dir), volume=0.5),
    )

    async def provision(path: Path) -> None:
        calls.append(path)
        started.set()
        await release.wait()
        path.mkdir(parents=True)
        (path / TEST_SID_NAME).write_bytes(SID_BYTES)

    monkeypatch.setattr(manager_mod, "provision_hvsc_corpus_async", provision)
    daemon = SimpleNamespace(chiptunes_manager=manager)

    TeleClaudeDaemon._apply_chiptunes_startup_state(daemon)
    TeleClaudeDaemon._apply_chiptunes_startup_state(daemon)
    await asyncio.wait_for(started.wait(), timeout=1)
    assert manager.enabled is False

    release.set()
    task = manager._provision_task
    assert task is not None
    await asyncio.wait_for(task, timeout=1)

    assert calls == [music_dir]
    assert manager.enabled is True
