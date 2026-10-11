"""Read and normalize the application's release-owned metadata."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from git.objects.blob import Blob

from teleclaude.git import Repo

_PROJECT_FILE = "pyproject.toml"
_LOCK_FILE = "uv.lock"
_CHANGELOG_FILE = "CHANGELOG.md"
_PROVENANCE_FILE = "release-provenance.json"
_MANIFEST_FILES = frozenset(
    {
        "manifests/cli-surface.md",
        "manifests/events.md",
        "manifests/config.md",
    }
)
_RELEASE_OWNED_FILES = _MANIFEST_FILES | frozenset({_CHANGELOG_FILE, _PROVENANCE_FILE})
_PROJECT_TABLE = "[project]"
_PACKAGE_TABLE = "[[package]]"
_VERSION_KEY = "version"
_NAME_KEY = "name"
_SOURCE_KEY = "source"
_PROJECT_TABLE_KEY = "project"
_PACKAGE_LIST_KEY = "package"
_EDITABLE_KEY = "editable"
_APP_PACKAGE = "teleclaude"
_EDITABLE_SOURCE = "."
_NORMALIZED_VERSION_VALUE = "<application-version>"
_UTF8_ENCODING = "utf-8"
_ASCII_ENCODING = "ascii"
_OCTAL_FORMAT = "o"
_TABLE_PREFIX = "["
_TABLE_NAME_QUOTE = '"'
_SINGLE_QUOTE = "'"
_ASSIGNMENT_SEPARATOR = "="
_HASH_SEPARATOR = b"\0"
_TREE_PATH_PREFIX = "./"
_EMPTY_TEXT = ""
_INVALID_TOML = "Release metadata is not valid TOML."
_MISSING_PROJECT_VERSION = "pyproject.toml must declare a string project.version."
_MISSING_LOCK_VERSION = "uv.lock must contain one editable TeleClaude package record."
_VERSION_ASSIGNMENT_MISSING = "The parsed application version has no source assignment."


def read_project_version(source: str | Path) -> str:
    """Read the application version from a pyproject file or repository root."""
    path = Path(source)
    pyproject = path / _PROJECT_FILE if path.is_dir() else path
    try:
        document = tomllib.loads(pyproject.read_text(encoding=_UTF8_ENCODING))
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError(_INVALID_TOML) from None
    project = document.get(_PROJECT_TABLE_KEY)
    version = project.get(_VERSION_KEY) if isinstance(project, dict) else None
    if not isinstance(version, str):
        raise ValueError(_MISSING_PROJECT_VERSION)
    return version


def read_locked_project_version(source: str | Path) -> str:
    """Read the single editable TeleClaude version recorded in uv.lock."""
    path = Path(source)
    lock = path / _LOCK_FILE if path.is_dir() else path
    try:
        document = tomllib.loads(lock.read_text(encoding=_UTF8_ENCODING))
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError(_INVALID_TOML) from None
    rows = document.get(_PACKAGE_LIST_KEY)
    packages = rows if isinstance(rows, list) else []
    matches = [
        package
        for package in packages
        if isinstance(package, dict)
        and package.get(_NAME_KEY) == _APP_PACKAGE
        and isinstance(package.get(_SOURCE_KEY), dict)
        and package[_SOURCE_KEY].get(_EDITABLE_KEY) == _EDITABLE_SOURCE
    ]
    if len(matches) != 1 or not isinstance(matches[0].get(_VERSION_KEY), str):
        raise ValueError(_MISSING_LOCK_VERSION)
    return str(matches[0][_VERSION_KEY])


def normalize_release_owned_file(path: str, content: bytes) -> bytes | None:
    """Remove generated release outputs or normalize only application version fields."""
    if path in _RELEASE_OWNED_FILES:
        return None
    if path == _PROJECT_FILE:
        return _normalize_project_version(content)
    if path == _LOCK_FILE:
        return _normalize_lock_version(content)
    return content


def set_project_version(content: bytes, version: str) -> bytes:
    """Replace only the parsed [project].version scalar in pyproject metadata."""
    try:
        document = tomllib.loads(content.decode(_UTF8_ENCODING))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ValueError(_INVALID_TOML) from None
    project = document.get(_PROJECT_TABLE_KEY)
    if not isinstance(project, dict) or not isinstance(project.get(_VERSION_KEY), str):
        raise ValueError(_MISSING_PROJECT_VERSION)
    lines = content.decode(_UTF8_ENCODING).splitlines(keepends=True)
    in_project = False
    replacements = 0
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(_TABLE_PREFIX):
            in_project = stripped == _PROJECT_TABLE
        key, separator, _ = line.partition(_ASSIGNMENT_SEPARATOR)
        if in_project and separator and key.strip().strip(_TABLE_NAME_QUOTE) == _VERSION_KEY:
            result.append(_replace_assignment_value(line, version))
            replacements += 1
        else:
            result.append(line)
    if replacements != 1:
        raise ValueError(_VERSION_ASSIGNMENT_MISSING)
    updated = _EMPTY_TEXT.join(result).encode(_UTF8_ENCODING)
    try:
        updated_document = tomllib.loads(updated.decode(_UTF8_ENCODING))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ValueError(_INVALID_TOML) from None
    updated_project = updated_document.get(_PROJECT_TABLE_KEY)
    if not isinstance(updated_project, dict) or updated_project.get(_VERSION_KEY) != version:
        raise ValueError(_VERSION_ASSIGNMENT_MISSING)
    return updated


def set_locked_project_version(content: bytes, version: str) -> bytes:
    """Replace only the editable TeleClaude package version in uv.lock."""
    text = content.decode(_UTF8_ENCODING)
    try:
        document = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ValueError(_INVALID_TOML) from None
    rows = document.get(_PACKAGE_LIST_KEY)
    packages = rows if isinstance(rows, list) else []
    matches = [
        package
        for package in packages
        if isinstance(package, dict)
        and package.get(_NAME_KEY) == _APP_PACKAGE
        and isinstance(package.get(_SOURCE_KEY), dict)
        and package[_SOURCE_KEY].get(_EDITABLE_KEY) == _EDITABLE_SOURCE
    ]
    if len(matches) != 1 or not isinstance(matches[0].get(_VERSION_KEY), str):
        raise ValueError(_MISSING_LOCK_VERSION)
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.strip() == _PACKAGE_TABLE and current:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    result: list[str] = []
    replacements = 0
    for block in blocks:
        try:
            block_document = tomllib.loads(_EMPTY_TEXT.join(block))
        except tomllib.TOMLDecodeError:
            result.extend(block)
            continue
        package_rows = block_document.get(_PACKAGE_LIST_KEY)
        package = package_rows[0] if isinstance(package_rows, list) and package_rows else None
        source = package.get(_SOURCE_KEY) if isinstance(package, dict) else None
        is_root = (
            isinstance(package, dict)
            and package.get(_NAME_KEY) == _APP_PACKAGE
            and isinstance(source, dict)
            and source.get(_EDITABLE_KEY) == _EDITABLE_SOURCE
        )
        if not is_root:
            result.extend(block)
            continue
        for line in block:
            key, separator, _ = line.partition(_ASSIGNMENT_SEPARATOR)
            if separator and key.strip() == _VERSION_KEY:
                result.append(_replace_assignment_value(line, version))
                replacements += 1
            else:
                result.append(line)
    if replacements != 1:
        raise ValueError(_VERSION_ASSIGNMENT_MISSING)
    updated = _EMPTY_TEXT.join(result).encode(_UTF8_ENCODING)
    if _read_locked_version_bytes(updated) != version:
        raise ValueError(_MISSING_LOCK_VERSION)
    return updated


def normalized_tree_digest(repo: Repo, revision: str) -> str:
    """Hash a Git tree after removing only explicitly release-owned metadata."""
    digest = hashlib.sha256()
    commit = repo.commit(revision)
    for item in commit.tree.traverse():
        if not isinstance(item, Blob):
            continue
        path = str(item.path).removeprefix(_TREE_PATH_PREFIX)
        normalized = normalize_release_owned_file(path, item.data_stream.read())
        if normalized is None:
            continue
        digest.update(path.encode(_UTF8_ENCODING))
        digest.update(_HASH_SEPARATOR)
        digest.update(format(item.mode, _OCTAL_FORMAT).encode(_ASCII_ENCODING))
        digest.update(_HASH_SEPARATOR)
        digest.update(normalized)
        digest.update(_HASH_SEPARATOR)
    return digest.hexdigest()


def _normalize_project_version(content: bytes) -> bytes:
    """Replace only the version assignment inside the project table."""
    text = content.decode(_UTF8_ENCODING)
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError(_INVALID_TOML) from None
    project = document.get(_PROJECT_TABLE_KEY)
    version = project.get(_VERSION_KEY) if isinstance(project, dict) else None
    if not isinstance(version, str):
        raise ValueError(_MISSING_PROJECT_VERSION)
    lines = text.splitlines(keepends=True)
    in_project = False
    replacements = 0
    normalized: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(_TABLE_PREFIX):
            in_project = stripped == _PROJECT_TABLE
        key, separator, _ = line.partition(_ASSIGNMENT_SEPARATOR)
        if in_project and separator and key.strip().strip(_TABLE_NAME_QUOTE) == _VERSION_KEY:
            normalized.append(_normalize_assignment_value(line))
            replacements += 1
        else:
            normalized.append(line)
    if replacements != 1:
        raise ValueError(_VERSION_ASSIGNMENT_MISSING)
    return _EMPTY_TEXT.join(normalized).encode(_UTF8_ENCODING)


def _normalize_lock_version(content: bytes) -> bytes:
    """Replace only the version of the editable root package in uv.lock."""
    text = content.decode(_UTF8_ENCODING)
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError(_INVALID_TOML) from None
    package_rows = document.get(_PACKAGE_LIST_KEY)
    packages = package_rows if isinstance(package_rows, list) else []
    matches = [
        package
        for package in packages
        if isinstance(package, dict)
        and package.get(_NAME_KEY) == _APP_PACKAGE
        and isinstance(package.get(_SOURCE_KEY), dict)
        and package[_SOURCE_KEY].get(_EDITABLE_KEY) == _EDITABLE_SOURCE
    ]
    if len(matches) != 1:
        raise ValueError(_MISSING_LOCK_VERSION)
    lines = text.splitlines(keepends=True)
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip() == _PACKAGE_TABLE and current:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    replacements = 0
    normalized: list[str] = []
    for block in blocks:
        block_text = _EMPTY_TEXT.join(block)
        try:
            package_document = tomllib.loads(block_text)
        except tomllib.TOMLDecodeError:
            normalized.extend(block)
            continue
        package_rows = package_document.get(_PACKAGE_LIST_KEY)
        package_row = package_rows[0] if isinstance(package_rows, list) and package_rows else None
        source = package_row.get(_SOURCE_KEY) if isinstance(package_row, dict) else None
        is_root = (
            isinstance(package_row, dict)
            and package_row.get(_NAME_KEY) == _APP_PACKAGE
            and isinstance(source, dict)
            and source.get(_EDITABLE_KEY) == _EDITABLE_SOURCE
        )
        if not is_root:
            normalized.extend(block)
            continue
        for line in block:
            key, separator, _ = line.partition(_ASSIGNMENT_SEPARATOR)
            if separator and key.strip() == _VERSION_KEY:
                normalized.append(_normalize_assignment_value(line))
                replacements += 1
            else:
                normalized.append(line)
    if replacements != 1:
        raise ValueError(_MISSING_LOCK_VERSION)
    return _EMPTY_TEXT.join(normalized).encode(_UTF8_ENCODING)


def _normalize_assignment_value(line: str) -> str:
    """Replace one quoted scalar value while preserving surrounding source text."""
    return _replace_assignment_value(line, _NORMALIZED_VERSION_VALUE)


def _replace_assignment_value(line: str, replacement: str) -> str:
    """Replace a quoted scalar while preserving key, spacing, quote and line ending."""
    prefix, separator, value = line.partition(_ASSIGNMENT_SEPARATOR)
    leading = value[: len(value) - len(value.lstrip())]
    scalar = value.lstrip()
    quote = scalar[0]
    value_end = scalar.find(quote, 1)
    if not separator or quote not in {_TABLE_NAME_QUOTE, _SINGLE_QUOTE} or value_end < 0:
        raise ValueError(_VERSION_ASSIGNMENT_MISSING)
    return prefix + separator + leading + quote + replacement + quote + scalar[value_end + 1 :]


def _read_locked_version_bytes(content: bytes) -> str:
    """Read the editable package version from one validated lockfile payload."""
    try:
        document = tomllib.loads(content.decode(_UTF8_ENCODING))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise ValueError(_INVALID_TOML) from None
    rows = document.get(_PACKAGE_LIST_KEY)
    packages = rows if isinstance(rows, list) else []
    matches = [
        package
        for package in packages
        if isinstance(package, dict)
        and package.get(_NAME_KEY) == _APP_PACKAGE
        and isinstance(package.get(_SOURCE_KEY), dict)
        and package[_SOURCE_KEY].get(_EDITABLE_KEY) == _EDITABLE_SOURCE
    ]
    if len(matches) != 1 or not isinstance(matches[0].get(_VERSION_KEY), str):
        raise ValueError(_MISSING_LOCK_VERSION)
    return str(matches[0][_VERSION_KEY])
