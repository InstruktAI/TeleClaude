"""On-demand HVSC corpus provisioning."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from instrukt_ai_logging import get_logger

try:
    import libarchive

    _libarchive_available = True
except (ImportError, OSError, AttributeError):
    # libarchive-c loads the system libarchive when imported: a missing package raises ImportError, a named library
    # that does not exist raises OSError, and a host without any libarchive raises AttributeError on the first symbol.
    libarchive = None  # type: ignore[unused-ignore]
    _libarchive_available = False

if TYPE_CHECKING:
    from libarchive.entry import ArchiveEntry

logger = get_logger(__name__)

MANIFEST_PATH = Path(__file__).with_name("hvsc_manifest.json")
ProvisionStatus = Literal["skipped", "installed"]
PROVISION_SKIPPED: ProvisionStatus = "skipped"
PROVISION_INSTALLED: ProvisionStatus = "installed"
HVSC_DOWNLOADS_URL = "https://www.hvsc.c64.org/downloads"
_REPAIR_POINTER = "The archive is pinned by {manifest}; current HVSC releases are listed at {downloads}."
_DOWNLOAD_FAILED_MESSAGE = "Failed to download HVSC archive from {url}. " + _REPAIR_POINTER
_CHECKSUM_MISMATCH_MESSAGE = (
    "Downloaded HVSC archive checksum mismatch; refusing to install corpus "
    "(expected {expected}, got {actual}). " + _REPAIR_POINTER
)
_EXTRACTOR_UNAVAILABLE_MESSAGE = (
    "The libarchive shared library is required to extract the HVSC .7z archive. "
    "It is part of macOS; install `libarchive-tools` on Debian/Ubuntu or `libarchive` on Fedora/Arch, "
    "and run `uv sync` so the libarchive-c binding is present."
)
_EXTRACT_FAILED_MESSAGE = "Failed to extract HVSC archive into {target}: {error}"
_STAGING_NAME = ".{name}.provisioning-{token}"
_STAGING_CLEANUP_FAILED_EVENT = "chiptunes_provision_staging_cleanup_failed"


class ChiptunesProvisionError(RuntimeError):
    """Base error for chiptunes corpus provisioning failures."""


class ChiptunesChecksumError(ChiptunesProvisionError):
    """Raised when the downloaded archive does not match the pinned checksum."""


class ChiptunesExtractorUnavailable(ChiptunesProvisionError):
    """Raised when the libarchive library or its Python binding is unavailable."""


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
            raise ChiptunesProvisionError(
                _DOWNLOAD_FAILED_MESSAGE.format(
                    url=manifest.archive_url, manifest=manifest_path, downloads=HVSC_DOWNLOADS_URL
                )
            ) from exc
        actual_sha256 = _sha256_file(archive_path)
        if actual_sha256 != manifest.sha256:
            logger.error(
                "chiptunes_provision_checksum_mismatch",
                expected=manifest.sha256,
                actual=actual_sha256,
                url=manifest.archive_url,
                manifest=str(manifest_path),
                downloads=HVSC_DOWNLOADS_URL,
            )
            raise ChiptunesChecksumError(
                _CHECKSUM_MISMATCH_MESSAGE.format(
                    expected=manifest.sha256,
                    actual=actual_sha256,
                    manifest=manifest_path,
                    downloads=HVSC_DOWNLOADS_URL,
                )
            )
        _publish_corpus(archive_path, music_dir)
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


def _publish_corpus(archive_path: Path, music_dir: Path) -> None:
    """Extract ``archive_path`` into a sibling staging directory and rename it onto ``music_dir``.

    ``music_dir`` is absent or empty here. It is written only by the final rename, which is atomic within one
    filesystem, so a failure at any earlier point leaves it exactly as it was.
    """
    staging_dir = music_dir.parent / _STAGING_NAME.format(name=music_dir.name, token=uuid4().hex)
    published = False
    try:
        music_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir()
        _extract_archive(archive_path, staging_dir)
        os.replace(staging_dir, music_dir)
        published = True
    except OSError as exc:
        raise ChiptunesProvisionError(_EXTRACT_FAILED_MESSAGE.format(target=music_dir, error=exc)) from exc
    finally:
        if not published:
            _discard_staging(staging_dir)


def _discard_staging(staging_dir: Path) -> None:
    try:
        shutil.rmtree(staging_dir)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning(_STAGING_CLEANUP_FAILED_EVENT, staging_dir=str(staging_dir), error=str(exc))


def _extract_archive(archive_path: Path, target_dir: Path) -> None:
    if not _libarchive_available:
        raise ChiptunesExtractorUnavailable(_EXTRACTOR_UNAVAILABLE_MESSAGE)
    # Entries are written under ``target_dir`` by rewriting their pathnames: ``libarchive.extract_file`` extracts into
    # the process working directory, which must not move under the daemon's other threads.
    flags = libarchive.extract.EXTRACT_SECURE_NODOTDOT | libarchive.extract.EXTRACT_SECURE_SYMLINKS
    try:
        with libarchive.file_reader(str(archive_path)) as entries:
            libarchive.extract.extract_entries(_corpus_entries_under(entries, target_dir), flags=flags)
    except (libarchive.exception.ArchiveError, OSError) as exc:
        raise ChiptunesProvisionError(_EXTRACT_FAILED_MESSAGE.format(target=target_dir, error=exc)) from exc


def _corpus_entries_under(entries: Iterable[ArchiveEntry], target_dir: Path) -> Iterator[ArchiveEntry]:
    """Yield each entry with its pathname moved under ``target_dir``, minus the archive's leading root element.

    The pinned archive has a single ``C64Music/`` root; the corpus tree belongs directly in ``target_dir``. The
    root's own entry has nothing left after the strip and is skipped.
    """
    for entry in entries:
        relative = PurePosixPath(*PurePosixPath(entry.pathname).parts[1:])
        if not relative.parts:
            continue
        entry.pathname = str(target_dir / relative)
        yield entry
