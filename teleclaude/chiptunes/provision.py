"""On-demand HVSC corpus provisioning."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

MANIFEST_PATH = Path(__file__).with_name("hvsc_manifest.json")
ProvisionStatus = Literal["skipped", "installed"]
PROVISION_SKIPPED: ProvisionStatus = "skipped"
PROVISION_INSTALLED: ProvisionStatus = "installed"


class ChiptunesProvisionError(RuntimeError):
    """Base error for chiptunes corpus provisioning failures."""


class ChiptunesChecksumError(ChiptunesProvisionError):
    """Raised when the downloaded archive does not match the pinned checksum."""


class ChiptunesExtractorUnavailable(ChiptunesProvisionError):
    """Raised when the required 7z extractor dependency is unavailable."""


@dataclass(frozen=True)
class HvscManifest:
    version: int
    archive_url: str
    sha256: str


@dataclass(frozen=True)
class ProvisionResult:
    status: ProvisionStatus
    music_dir: Path


def provision_hvsc_corpus(
    music_dir: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> ProvisionResult:
    """Install the pinned HVSC archive into ``music_dir`` when it is absent."""
    if _is_populated_dir(music_dir):
        logger.info("chiptunes_provision_skip", music_dir=str(music_dir), reason="populated")
        return ProvisionResult(status=PROVISION_SKIPPED, music_dir=music_dir)

    manifest = load_manifest(manifest_path)
    with tempfile.TemporaryDirectory(prefix="teleclaude-hvsc-") as temp_dir:
        archive_path = Path(temp_dir) / "hvsc.7z"
        try:
            _download_archive(manifest.archive_url, archive_path)
        except (urllib.error.URLError, OSError) as exc:
            raise ChiptunesProvisionError(f"Failed to download HVSC archive from {manifest.archive_url}.") from exc
        actual_sha256 = _sha256_file(archive_path)
        if actual_sha256 != manifest.sha256:
            logger.error(
                "chiptunes_provision_checksum_mismatch",
                expected=manifest.sha256,
                actual=actual_sha256,
                url=manifest.archive_url,
            )
            raise ChiptunesChecksumError(
                "Downloaded HVSC archive checksum mismatch; refusing to install corpus "
                f"(expected {manifest.sha256}, got {actual_sha256})."
            )
        music_dir.mkdir(parents=True, exist_ok=True)
        try:
            _extract_archive(archive_path, music_dir)
        except ChiptunesProvisionError:
            raise
        except OSError as exc:
            raise ChiptunesProvisionError(f"Failed to extract HVSC archive into {music_dir}.") from exc
    logger.info("chiptunes_provision_installed", music_dir=str(music_dir), version=manifest.version)
    return ProvisionResult(status=PROVISION_INSTALLED, music_dir=music_dir)


async def provision_hvsc_corpus_async(
    music_dir: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> ProvisionResult:
    """Install the pinned HVSC archive without blocking the event loop."""
    return await asyncio.to_thread(provision_hvsc_corpus, music_dir, manifest_path=manifest_path)


def load_manifest(path: Path = MANIFEST_PATH) -> HvscManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ChiptunesProvisionError(f"HVSC manifest must be a JSON object: {path}")
    return _parse_manifest(raw, path)


def _parse_manifest(raw: dict[str, object], path: Path) -> HvscManifest:  # guard: loose-dict
    try:
        version = raw["version"]
        archive_url = raw["archive_url"]
        sha256 = raw["sha256"]
    except KeyError as exc:
        raise ChiptunesProvisionError(f"Invalid HVSC manifest: {path}") from exc
    if not isinstance(version, int) or not isinstance(archive_url, str) or not isinstance(sha256, str):
        raise ChiptunesProvisionError(f"Invalid HVSC manifest: {path}")
    if not archive_url or not sha256:
        raise ChiptunesProvisionError(f"Invalid HVSC manifest: {path}")
    return HvscManifest(version=version, archive_url=archive_url, sha256=sha256)


def _is_populated_dir(path: Path) -> bool:
    if not path.exists():
        return False
    if not path.is_dir():
        raise ChiptunesProvisionError(f"Chiptunes music path exists but is not a directory: {path}")
    return any(path.iterdir())


def _download_archive(url: str, target: Path) -> None:
    logger.info("chiptunes_provision_fetch", url=url, target=str(target))
    with urllib.request.urlopen(url) as response, target.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_archive(archive_path: Path, target_dir: Path) -> None:
    try:
        import py7zr  # noqa: PLC0415 - lazy dependency import; provisioning only runs when gate-enabled.
        from py7zr import exceptions as py7zr_exceptions  # noqa: PLC0415 - lazy dependency import; same gate.
    except ImportError as exc:
        raise ChiptunesExtractorUnavailable(
            "py7zr is required to extract the HVSC .7z archive. "
            "Run `uv sync` or reinstall TeleClaude so default runtime dependencies are present."
        ) from exc
    try:
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            archive.extractall(path=target_dir)
    except (py7zr.Bad7zFile, py7zr_exceptions.ArchiveError, OSError) as exc:
        raise ChiptunesProvisionError(f"Failed to extract HVSC archive into {target_dir}.") from exc
