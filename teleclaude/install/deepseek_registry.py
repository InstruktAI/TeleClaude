"""Registry and installed-runtime effects behind the DeepSeek stack fit decision.

Executes only: version lists and declared requirements come from the package registry,
range resolution is the registry's own (``npm view``), and the version a candidate
runtime brings for a library is read from a runtime tree. Nothing here decides fit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from instrukt_ai_logging import get_logger

from teleclaude.core.reconciliation.deepseek_fit import (
    LOCAL_REFERENCE_PREFIX,
    RUNTIME_ENGINE,
    RUNTIME_PACKAGE,
    DeepSeekStackError,
    PackageRequirements,
    PackageSource,
    package_source,
    registry_reference,
)

logger = get_logger(__name__)

_NPM = "npm"
_NPM_CONFIG = "config"
_NPM_GET = "get"
_NPM_REGISTRY_KEY = "registry"
_NPM_ROOT = "root"
_NPM_PREFIX = "prefix"
NPM_GLOBAL_FLAG = "-g"
_NPM_VIEW = "view"
_NPM_VERSION_FIELD = "version"
_NPM_JSON_FLAG = "--json"
NPM_INSTALL_COMMAND = "install"
_NPM_PREFIX_FLAG = "--prefix"
_NPM_STAGE_FLAGS = ("--ignore-scripts", "--no-audit", "--no-fund")
_NPM_NO_MATCH_CODE = "E404"
_NPM_QUERY_FAILURE_TEMPLATE = "npm query {query} failed: {detail}"
_NPM_UNAVAILABLE = "npm is not installed or not on PATH"
_NPM_TIMEOUT_TEMPLATE = "npm {action} timed out after {seconds} seconds"
_NPM_QUERY_TIMEOUT_SECONDS = 60
_NPM_STAGE_TIMEOUT_SECONDS = 600
_NPM_PATH_TIMEOUT_SECONDS = 30
NPM_INSTALL_TIMEOUT_SECONDS = 600
_DETAIL_TAIL_CHARS = 400

_REGISTRY_SCHEME = "https"
_REGISTRY_ACCEPT = "application/vnd.npm.install-v1+json"
_REGISTRY_ACCEPT_HEADER = "Accept"
_REGISTRY_FETCH_TIMEOUT_SECONDS = 60
_REGISTRY_SCOPE_PREFIX = "@"
_REGISTRY_SCOPE_SEPARATOR = "/"
_REGISTRY_ENCODED_SEPARATOR = "%2f"
_REGISTRY_URL_SEPARATOR = "/"
_REGISTRY_INSECURE_TEMPLATE = "The configured npm registry {url} is not an https URL"
_REGISTRY_FETCH_FAILURE_TEMPLATE = "Registry fetch for {name} failed: {error}"
_REGISTRY_SHAPE_TEMPLATE = "Registry metadata for {name} is not the expected shape: {detail}"
_PACKUMENT_VERSIONS = "versions"
_MANIFEST_PEERS = "peerDependencies"
_MANIFEST_ENGINES = "engines"
_MANIFEST_VERSION = "version"
MANIFEST_FILENAME = "package.json"
NODE_MODULES_DIRECTORY = "node_modules"
_LOCAL_REFERENCE_TEMPLATE = "Local plugin reference {reference} is not an absolute file: path"
_MANIFEST_UNREADABLE_TEMPLATE = "Cannot read manifest {path}: {error}"
_STAGE_FAILURE_TEMPLATE = "Staging runtime {version} to read its bundled libraries failed: {detail}"
_STAGE_DIRECTORY = "candidates"
_JSON_ENCODING = "utf-8"
_ERROR_KEY = "error"
_ERROR_CODE_KEY = "code"
_FIELD_LABEL = "{label} {key}"
_UNEXPECTED_JSON_TEMPLATE = "{what} is {kind}, expected {expected}"
_EXPECTED_OBJECT = "an object"
_EXPECTED_STRING = "a string"
_EXPECTED_QUERY_RESULT = "a version string or a list of them"
_LOG_STAGE_COMPLETE = "DeepSeek candidate runtime staged"
_MILLISECONDS_PER_SECOND = 1_000


@dataclass(frozen=True)
class NpmResult:
    """The outcome of one npm invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def detail(self) -> str:
        """The tail of the diagnostic output, for an error message."""
        return (self.stderr or self.stdout).strip()[-_DETAIL_TAIL_CHARS:]


def run_npm(arguments: Sequence[str], *, timeout_seconds: int) -> NpmResult:
    """Run npm with an argument list and no terminal input.

    npm owns range resolution, global installation and its own configuration; Python has
    no equivalent API for any of them. stdin is closed so no npm prompt can wait on, or
    be answered by, an operator.
    """
    executable = shutil.which(_NPM)
    if executable is None:
        raise DeepSeekStackError(_NPM_UNAVAILABLE)
    try:
        completed = subprocess.run(
            (executable, *arguments),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise DeepSeekStackError(_NPM_TIMEOUT_TEMPLATE.format(action=arguments[0], seconds=timeout_seconds)) from error
    return NpmResult(completed.returncode, completed.stdout, completed.stderr)


def npm_global_root() -> Path:
    """The directory npm installs global packages into."""
    return Path(_npm_path_output((_NPM_ROOT, NPM_GLOBAL_FLAG)))


def npm_global_prefix() -> Path:
    """The prefix npm links global executables under."""
    return Path(_npm_path_output((_NPM_PREFIX, NPM_GLOBAL_FLAG)))


def installed_runtime_directory() -> Path:
    """Where the global runtime package lives when installed."""
    return npm_global_root() / RUNTIME_PACKAGE


def _npm_path_output(arguments: Sequence[str]) -> str:
    result = run_npm(arguments, timeout_seconds=_NPM_PATH_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise DeepSeekStackError(_NPM_QUERY_FAILURE_TEMPLATE.format(query=arguments[0], detail=result.detail))
    return result.stdout.strip()


class RegistryCompatibilityView:
    """The fit decision's registry facts, read from the package registry and runtime trees.

    Every answer is cached for the life of the instance, which is one convergence run.
    ``scratch_directory`` is the run's own area; staged candidate runtimes live under it.
    """

    def __init__(self, scratch_directory: Path) -> None:
        self._scratch_directory = scratch_directory
        self._registry_url: str | None = None
        self._packuments: dict[str, dict[str, PackageRequirements]] = {}
        self._satisfying: dict[tuple[str, str], frozenset[str]] = {}
        self._runtime_directories: dict[str, Path] = {}

    def runtime_versions(self) -> Sequence[str]:
        """Every published runtime version, across release channels."""
        return self.published_versions(RUNTIME_PACKAGE)

    def published_versions(self, name: str) -> Sequence[str]:
        """Every published version of a package, in no particular order."""
        return tuple(self._packument(name))

    def requirements(self, name: str, version: str) -> PackageRequirements:
        """The peer and runtime-engine ranges a published package version declares."""
        return self._packument(name)[version]

    def local_requirements(self, reference: str) -> PackageRequirements:
        """The peer and runtime-engine ranges in the manifest a ``file:`` reference points at."""
        if package_source(reference) is not PackageSource.LOCAL_CHECKOUT:
            raise DeepSeekStackError(_LOCAL_REFERENCE_TEMPLATE.format(reference=reference))
        path = Path(reference.removeprefix(LOCAL_REFERENCE_PREFIX))
        if not path.is_absolute():
            raise DeepSeekStackError(_LOCAL_REFERENCE_TEMPLATE.format(reference=reference))
        return _requirements_of(read_manifest(path / MANIFEST_FILENAME), reference)

    def satisfies(self, requirement_name: str, version: str, requirement_range: str) -> bool:
        """Whether the registry resolves the range to include the version."""
        return version in self._satisfying_versions(requirement_name, requirement_range)

    def brought_version(self, candidate: str, requirement_name: str) -> str | None:
        """The version of a package the candidate runtime supplies, or ``None`` when it supplies none."""
        runtime_directory = self._runtime_directory(candidate)
        for directory in (runtime_directory, *runtime_directory.parents):
            if directory.name == NODE_MODULES_DIRECTORY:
                continue
            manifest = directory / NODE_MODULES_DIRECTORY / requirement_name / MANIFEST_FILENAME
            if manifest.is_file():
                return string_field(read_manifest(manifest), _MANIFEST_VERSION, str(manifest))
        return None

    def _runtime_directory(self, candidate: str) -> Path:
        """The installed runtime when it is the candidate, else the candidate staged once into scratch."""
        known = self._runtime_directories.get(candidate)
        if known is not None:
            return known
        installed = installed_runtime_directory()
        installed_manifest = installed / MANIFEST_FILENAME
        if (
            installed_manifest.is_file()
            and string_field(read_manifest(installed_manifest), _MANIFEST_VERSION, str(installed_manifest)) == candidate
        ):
            self._runtime_directories[candidate] = installed
            return installed
        staged = self._stage(candidate)
        self._runtime_directories[candidate] = staged
        return staged

    def _stage(self, candidate: str) -> Path:
        prefix = self._scratch_directory / _STAGE_DIRECTORY / candidate
        started_at = time.monotonic()
        result = run_npm(
            (
                NPM_INSTALL_COMMAND,
                _NPM_PREFIX_FLAG,
                str(prefix),
                *_NPM_STAGE_FLAGS,
                registry_reference(RUNTIME_PACKAGE, candidate),
            ),
            timeout_seconds=_NPM_STAGE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise DeepSeekStackError(_STAGE_FAILURE_TEMPLATE.format(version=candidate, detail=result.detail))
        logger.debug(
            _LOG_STAGE_COMPLETE,
            version=candidate,
            prefix=str(prefix),
            duration_ms=(time.monotonic() - started_at) * _MILLISECONDS_PER_SECOND,
        )
        return prefix / NODE_MODULES_DIRECTORY / RUNTIME_PACKAGE

    def _satisfying_versions(self, name: str, requirement_range: str) -> frozenset[str]:
        key = (name, requirement_range)
        known = self._satisfying.get(key)
        if known is not None:
            return known
        query = registry_reference(name, requirement_range)
        result = run_npm(
            (_NPM_VIEW, query, _NPM_VERSION_FIELD, _NPM_JSON_FLAG), timeout_seconds=_NPM_QUERY_TIMEOUT_SECONDS
        )
        versions = _parse_view_result(result, query)
        self._satisfying[key] = versions
        return versions

    def _packument(self, name: str) -> dict[str, PackageRequirements]:
        known = self._packuments.get(name)
        if known is not None:
            return known
        document = self._fetch_packument(name)
        versions = document.get(_PACKUMENT_VERSIONS)
        if not isinstance(versions, dict):
            raise DeepSeekStackError(_REGISTRY_SHAPE_TEMPLATE.format(name=name, detail=_PACKUMENT_VERSIONS))
        parsed = {
            version: _requirements_of(manifest, registry_reference(name, version))
            for version, manifest in versions.items()
        }
        self._packuments[name] = parsed
        return parsed

    # guard: loose-dict-func - registry metadata is a dynamic external JSON shape, parsed at this boundary
    def _fetch_packument(self, name: str) -> dict[str, object]:
        url = self._registry_base() + _packument_path(name)
        request = urllib.request.Request(url, headers={_REGISTRY_ACCEPT_HEADER: _REGISTRY_ACCEPT})
        try:
            with urllib.request.urlopen(request, timeout=_REGISTRY_FETCH_TIMEOUT_SECONDS) as response:
                document = json.loads(response.read().decode(_JSON_ENCODING))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            raise DeepSeekStackError(_REGISTRY_FETCH_FAILURE_TEMPLATE.format(name=name, error=error)) from error
        if not isinstance(document, dict):
            raise DeepSeekStackError(_REGISTRY_SHAPE_TEMPLATE.format(name=name, detail=_EXPECTED_OBJECT))
        return document

    def _registry_base(self) -> str:
        if self._registry_url is None:
            result = run_npm((_NPM_CONFIG, _NPM_GET, _NPM_REGISTRY_KEY), timeout_seconds=_NPM_PATH_TIMEOUT_SECONDS)
            url = result.stdout.strip()
            if result.returncode != 0 or urlparse(url).scheme != _REGISTRY_SCHEME:
                raise DeepSeekStackError(_REGISTRY_INSECURE_TEMPLATE.format(url=url))
            self._registry_url = url.rstrip(_REGISTRY_URL_SEPARATOR) + _REGISTRY_URL_SEPARATOR
        return self._registry_url


def _packument_path(name: str) -> str:
    """The registry path of a package's metadata; a scoped name joins its scope with an encoded separator."""
    if name.startswith(_REGISTRY_SCOPE_PREFIX):
        return name.replace(_REGISTRY_SCOPE_SEPARATOR, _REGISTRY_ENCODED_SEPARATOR)
    return name


def _parse_view_result(result: NpmResult, query: str) -> frozenset[str]:
    """Read ``npm view <name>@<range> version --json``: a string or list, or the E404 no-match."""
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DeepSeekStackError(_NPM_QUERY_FAILURE_TEMPLATE.format(query=query, detail=result.detail)) from error
    if result.returncode != 0:
        if isinstance(document, dict) and _error_code(document) == _NPM_NO_MATCH_CODE:
            return frozenset()
        raise DeepSeekStackError(_NPM_QUERY_FAILURE_TEMPLATE.format(query=query, detail=result.detail))
    if isinstance(document, str):
        return frozenset((document,))
    if isinstance(document, list) and all(isinstance(item, str) for item in document):
        return frozenset(document)
    raise DeepSeekStackError(_NPM_QUERY_FAILURE_TEMPLATE.format(query=query, detail=_EXPECTED_QUERY_RESULT))


def _error_code(document: Mapping[str, object]) -> object:
    error = document.get(_ERROR_KEY)
    return error.get(_ERROR_CODE_KEY) if isinstance(error, dict) else None


# guard: loose-dict-func - a package manifest is a dynamic external JSON shape, parsed at this boundary
def read_manifest(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding=_JSON_ENCODING))
    except (OSError, json.JSONDecodeError) as error:
        raise DeepSeekStackError(_MANIFEST_UNREADABLE_TEMPLATE.format(path=path, error=error)) from error
    if not isinstance(document, dict):
        raise DeepSeekStackError(_MANIFEST_UNREADABLE_TEMPLATE.format(path=path, error=_EXPECTED_OBJECT))
    return document


def _requirements_of(manifest: object, label: str) -> PackageRequirements:
    """Parse a manifest's declared peer ranges and runtime engine range at the boundary."""
    if not isinstance(manifest, dict):
        raise DeepSeekStackError(_REGISTRY_SHAPE_TEMPLATE.format(name=label, detail=_EXPECTED_OBJECT))
    peers = string_mapping(manifest.get(_MANIFEST_PEERS), label)
    engines = string_mapping(manifest.get(_MANIFEST_ENGINES), label)
    return PackageRequirements(peers, engines.get(RUNTIME_ENGINE))


def string_mapping(value: object, label: str) -> Mapping[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DeepSeekStackError(
            _UNEXPECTED_JSON_TEMPLATE.format(what=label, kind=type(value).__name__, expected=_EXPECTED_OBJECT)
        )
    parsed: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise DeepSeekStackError(
                _UNEXPECTED_JSON_TEMPLATE.format(what=label, kind=type(item).__name__, expected=_EXPECTED_STRING)
            )
        parsed[key] = item
    return parsed


def string_field(manifest: Mapping[str, object], key: str, label: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str):
        raise DeepSeekStackError(
            _UNEXPECTED_JSON_TEMPLATE.format(
                what=_FIELD_LABEL.format(label=label, key=key), kind=type(value).__name__, expected=_EXPECTED_STRING
            )
        )
    return value
