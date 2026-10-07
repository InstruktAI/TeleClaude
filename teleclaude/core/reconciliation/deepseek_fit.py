"""Decision owner for which DeepSeek runtime, TUI and plugin versions fit together.

This module is pure: it reads the stack it is handed and asks one narrow
``CompatibilityView`` for registry facts. Range semantics stay with the package
registry (``CompatibilityView.satisfies``); only version *ordering* is decided here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

RUNTIME_PACKAGE = "@deepseek-ai/dsh"
RUNTIME_ENGINE = "dsh"
_RUNTIME_FAMILY_PREFIX = "@deepseek-ai/dsh-"
_WORKSPACE_RANGE_PREFIX = "workspace:"
_REGISTRY_REFERENCE_TEMPLATE = "{name}@{version}"


class _SemVerPart(StrEnum):
    """Named capture groups used to order a semantic version."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    PRERELEASE = "prerelease"


_SEMVER_PATTERN = re.compile(
    rf"^(?P<{_SemVerPart.MAJOR}>0|[1-9]\d*)\.(?P<{_SemVerPart.MINOR}>0|[1-9]\d*)"
    rf"\.(?P<{_SemVerPart.PATCH}>0|[1-9]\d*)"
    rf"(?:-(?P<{_SemVerPart.PRERELEASE}>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_PRERELEASE_SEPARATOR = "."
_NUMERIC_IDENTIFIER_PATTERN = re.compile(r"^(0|[1-9]\d*)$")
_INVALID_VERSION_TEMPLATE = "Not a semantic version: {version!r}"
_EMPTY_IDENTIFIER_TEXT = ""


class DeepSeekStackError(RuntimeError):
    """An operation error of the DeepSeek stack convergence: nothing was decided or changed by it."""


class PackageSource(StrEnum):
    """Where a profile's package comes from."""

    REGISTRY = "registry"
    LOCAL_CHECKOUT = "local_checkout"


@dataclass(frozen=True)
class StackPackage:
    """One dependency recorded in a profile's manifest."""

    name: str
    source: PackageSource
    reference: str
    installed_version: str | None


@dataclass(frozen=True)
class ProfileStack:
    """One runtime profile and the packages its manifest declares."""

    name: str
    packages: tuple[StackPackage, ...]


@dataclass(frozen=True)
class RequiredPlugin:
    """A plugin the installation requires every profile to hold.

    ``reference`` is the plugin manager's reference for a plugin from a local
    checkout, and ``None`` for a registry plugin, which is added at its adopted version.
    """

    name: str
    source: PackageSource
    reference: str | None


@dataclass(frozen=True)
class Stack:
    """The installed runtime, its profiles and the plugins the installation requires."""

    runtime_version: str | None
    profiles: tuple[ProfileStack, ...]
    required: tuple[RequiredPlugin, ...]


@dataclass(frozen=True)
class PackageRequirements:
    """What a package version declares it needs: peer ranges and the runtime engine range."""

    peers: Mapping[str, str]
    runtime_engine: str | None


@dataclass(frozen=True)
class Blocker:
    """One package that leaves a candidate runtime without a fit.

    ``requirement_name`` and ``requirement_range`` are the requirement the package
    declares and the candidate runtime fails; ``failing_version`` is the package
    version that declares it (the newest published one for a registry package).
    All three are ``None`` when the registry publishes no version of the package.
    """

    candidate: str
    package: str
    requirement_name: str | None
    requirement_range: str | None
    failing_version: str | None


@dataclass(frozen=True)
class Advisory:
    """A library requirement of an adopted package that the adopted runtime does not meet."""

    package: str
    version: str | None
    requirement_name: str
    requirement_range: str
    brought_version: str


@dataclass(frozen=True)
class PlannedPackage:
    """One package a profile is asked to add so that it holds the adopted set.

    ``adopted_version`` is the exact adopted version of a registry package and
    ``None`` for a plugin from a local checkout, which keeps its local reference.
    """

    name: str
    reference: str
    previous_reference: str | None
    previous_version: str | None
    adopted_version: str | None


@dataclass(frozen=True)
class Adoption:
    """The newest candidate runtime at which everything installed fits, and what moves to it."""

    runtime_version: str
    previous_runtime_version: str | None
    versions: Mapping[str, str]
    profiles: Mapping[str, tuple[PlannedPackage, ...]]
    advisories: tuple[Advisory, ...]
    rejected: tuple[Blocker, ...]

    @property
    def moves_runtime(self) -> bool:
        """Whether the runtime itself changes."""
        return self.runtime_version != self.previous_runtime_version

    @property
    def is_current(self) -> bool:
        """Whether the machine already holds this set: no runtime move and nothing to add."""
        return not self.moves_runtime and not any(self.profiles.values())


class CompatibilityView(Protocol):
    """The registry and manifest facts the fit decision reads."""

    def runtime_versions(self) -> Sequence[str]: ...

    def published_versions(self, name: str) -> Sequence[str]: ...

    def requirements(self, name: str, version: str) -> PackageRequirements: ...

    def local_requirements(self, reference: str) -> PackageRequirements: ...

    def brought_version(self, candidate: str, requirement_name: str) -> str | None: ...

    def satisfies(self, requirement_name: str, version: str, requirement_range: str) -> bool: ...


type _Precedence = tuple[int, int, int, int, tuple[tuple[int, int, str], ...]]


def version_precedence(version: str) -> _Precedence:
    """Order key for a semantic version, by SemVer 2.0.0 section 11 (build metadata ignored)."""
    match = _SEMVER_PATTERN.match(version)
    if match is None:
        raise DeepSeekStackError(_INVALID_VERSION_TEMPLATE.format(version=version))
    prerelease = match.group(_SemVerPart.PRERELEASE)
    identifiers = (
        () if prerelease is None else tuple(_identifier_key(part) for part in prerelease.split(_PRERELEASE_SEPARATOR))
    )
    return (
        int(match.group(_SemVerPart.MAJOR)),
        int(match.group(_SemVerPart.MINOR)),
        int(match.group(_SemVerPart.PATCH)),
        int(prerelease is None),
        identifiers,
    )


def _identifier_key(identifier: str) -> tuple[int, int, str]:
    if _NUMERIC_IDENTIFIER_PATTERN.match(identifier):
        return (0, int(identifier), _EMPTY_IDENTIFIER_TEXT)
    return (1, 0, identifier)


def registry_reference(name: str, version: str) -> str:
    """The exact registry reference a profile records for an adopted package version."""
    return _REGISTRY_REFERENCE_TEMPLATE.format(name=name, version=version)


def select_adoption(stack: Stack, view: CompatibilityView) -> Adoption | tuple[Blocker, ...]:
    """Pick the newest candidate runtime at which every installed package and required plugin fits.

    Returns the adoption of the first fitting candidate, newest first, carrying the
    blockers of every newer candidate it passed over; when no candidate fits, the
    blockers of every candidate.
    """
    passed_over: list[Blocker] = []
    for candidate in _candidates(stack, view):
        fit = _fit_candidate(stack, view, candidate)
        if isinstance(fit, _Fit):
            return Adoption(
                runtime_version=candidate,
                previous_runtime_version=stack.runtime_version,
                versions=fit.versions,
                profiles=_planned_profiles(stack, fit.versions, runtime_moves=candidate != stack.runtime_version),
                advisories=_advisories(view, candidate, fit),
                rejected=tuple(passed_over),
            )
        passed_over.extend(fit)
    return tuple(passed_over)


def _candidates(stack: Stack, view: CompatibilityView) -> tuple[str, ...]:
    """Published runtimes no older than the installed one, newest first; the installed one is always one."""
    installed = stack.runtime_version
    published = set(view.runtime_versions())
    if installed is not None:
        floor = version_precedence(installed)
        published = {version for version in published if version_precedence(version) >= floor}
        published.add(installed)
    return tuple(sorted(published, key=version_precedence, reverse=True))


@dataclass(frozen=True)
class _RegistryFit:
    """A registry package at the newest published version that fits, with what that version declares."""

    name: str
    version: str
    requirements: PackageRequirements


@dataclass(frozen=True)
class _LocalFit:
    """A local-checkout plugin whose own manifest fits."""

    name: str
    version: str | None
    requirements: PackageRequirements


@dataclass(frozen=True)
class _Fit:
    """Everything installed fits one candidate."""

    registry: tuple[_RegistryFit, ...]
    local: tuple[_LocalFit, ...]

    @property
    def versions(self) -> Mapping[str, str]:
        return {fitted.name: fitted.version for fitted in self.registry}


def _fit_candidate(stack: Stack, view: CompatibilityView, candidate: str) -> _Fit | tuple[Blocker, ...]:
    blockers: list[Blocker] = []
    registry: list[_RegistryFit] = []
    for name in _registry_names(stack):
        fitted = _newest_fitting_version(view, candidate, name)
        if isinstance(fitted, Blocker):
            blockers.append(fitted)
        else:
            registry.append(fitted)
    local: list[_LocalFit] = []
    for name, reference, version in _local_packages(stack):
        requirements = view.local_requirements(reference)
        failure = _first_runtime_failure(view, candidate, requirements)
        if failure is None:
            local.append(_LocalFit(name, version, requirements))
        else:
            blockers.append(Blocker(candidate, name, failure[0], failure[1], version))
    if blockers:
        return tuple(blockers)
    return _Fit(tuple(registry), tuple(local))


def _registry_names(stack: Stack) -> tuple[str, ...]:
    names = {
        package.name
        for profile in stack.profiles
        for package in profile.packages
        if package.source is PackageSource.REGISTRY
    }
    names.update(plugin.name for plugin in stack.required if plugin.source is PackageSource.REGISTRY)
    return tuple(sorted(names))


def _local_packages(stack: Stack) -> tuple[tuple[str, str, str | None], ...]:
    """Every distinct local-checkout reference with the package name and installed version it carries."""
    found: dict[str, tuple[str, str | None]] = {}
    for profile in stack.profiles:
        for package in profile.packages:
            if package.source is PackageSource.LOCAL_CHECKOUT:
                found.setdefault(package.reference, (package.name, package.installed_version))
    for plugin in stack.required:
        if plugin.source is PackageSource.LOCAL_CHECKOUT and plugin.reference is not None:
            found.setdefault(plugin.reference, (plugin.name, None))
    return tuple((name, reference, version) for reference, (name, version) in sorted(found.items()))


def _newest_fitting_version(view: CompatibilityView, candidate: str, name: str) -> _RegistryFit | Blocker:
    published = sorted(view.published_versions(name), key=version_precedence, reverse=True)
    if not published:
        return Blocker(candidate, name, None, None, None)
    newest, *older = published
    newest_requirements = view.requirements(name, newest)
    newest_failure = _first_runtime_failure(view, candidate, newest_requirements)
    if newest_failure is None:
        return _RegistryFit(name, newest, newest_requirements)
    for version in older:
        requirements = view.requirements(name, version)
        if _first_runtime_failure(view, candidate, requirements) is None:
            return _RegistryFit(name, version, requirements)
    return Blocker(candidate, name, newest_failure[0], newest_failure[1], newest)


def _runtime_requirements(requirements: PackageRequirements) -> tuple[tuple[str, str], ...]:
    """Requirements on the runtime itself: its own packages and its declared engine."""
    pairs = [(name, range_) for name, range_ in requirements.peers.items() if _is_runtime_family(name)]
    if requirements.runtime_engine is not None:
        pairs.append((RUNTIME_ENGINE, requirements.runtime_engine))
    return tuple(sorted(pairs))


def _library_requirements(requirements: PackageRequirements) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((name, range_) for name, range_ in requirements.peers.items() if not _is_runtime_family(name)))


def _is_runtime_family(name: str) -> bool:
    return name == RUNTIME_PACKAGE or name.startswith(_RUNTIME_FAMILY_PREFIX)


def _first_runtime_failure(
    view: CompatibilityView,
    candidate: str,
    requirements: PackageRequirements,
) -> tuple[str, str] | None:
    for name, requirement_range in _runtime_requirements(requirements):
        if requirement_range.startswith(_WORKSPACE_RANGE_PREFIX):
            continue
        if not view.satisfies(RUNTIME_PACKAGE, candidate, requirement_range):
            return (name, requirement_range)
    return None


def _planned_profiles(
    stack: Stack, versions: Mapping[str, str], *, runtime_moves: bool
) -> Mapping[str, tuple[PlannedPackage, ...]]:
    """Per profile, what must be added so it holds the adopted versions and every required plugin.

    A package already installed at its adopted version is written only to give every profile that holds it
    the same reference, and only when the run adopts something (UC-DSC5): then every package whose profiles
    disagree on its reference is brought to the exact adopted one. A set that is already installed stays
    untouched.
    """
    moving = _moving_packages(stack, versions)
    if runtime_moves or moving:
        moving = moving | _divergent_packages(stack)
    planned: dict[str, tuple[PlannedPackage, ...]] = {}
    for profile in stack.profiles:
        held = {package.name for package in profile.packages}
        additions = [
            _planned_registry_package(package, versions[package.name])
            for package in profile.packages
            if package.source is PackageSource.REGISTRY
            and package.name in moving
            and _differs_from_adopted(package, versions[package.name])
        ]
        for plugin in stack.required:
            if plugin.name in held:
                continue
            if plugin.source is PackageSource.LOCAL_CHECKOUT and plugin.reference is not None:
                additions.append(PlannedPackage(plugin.name, plugin.reference, None, None, None))
            else:
                additions.append(
                    PlannedPackage(
                        plugin.name,
                        registry_reference(plugin.name, versions[plugin.name]),
                        None,
                        None,
                        versions[plugin.name],
                    )
                )
        planned[profile.name] = tuple(additions)
    return planned


def _moving_packages(stack: Stack, versions: Mapping[str, str]) -> frozenset[str]:
    """Registry packages the run writes in at least one profile: a different version, or a required plugin to add."""
    moving: set[str] = set()
    for profile in stack.profiles:
        held = {package.name for package in profile.packages}
        moving.update(
            package.name
            for package in profile.packages
            if package.source is PackageSource.REGISTRY and package.installed_version != versions[package.name]
        )
        moving.update(plugin.name for plugin in stack.required if plugin.name not in held)
    return frozenset(moving)


def _divergent_packages(stack: Stack) -> frozenset[str]:
    """Registry packages that the profiles holding them reference through different specifiers."""
    references: dict[str, set[str]] = {}
    for profile in stack.profiles:
        for package in profile.packages:
            if package.source is PackageSource.REGISTRY:
                references.setdefault(package.name, set()).add(package.reference)
    return frozenset(name for name, held in references.items() if len(held) > 1)


def _differs_from_adopted(package: StackPackage, adopted_version: str) -> bool:
    return package.installed_version != adopted_version or package.reference != adopted_version


def _planned_registry_package(package: StackPackage, adopted_version: str) -> PlannedPackage:
    return PlannedPackage(
        package.name,
        registry_reference(package.name, adopted_version),
        package.reference,
        package.installed_version,
        adopted_version,
    )


def _advisories(view: CompatibilityView, candidate: str, fit: _Fit) -> tuple[Advisory, ...]:
    """Library requirements of the adopted packages that the candidate runtime brings a non-satisfying version for."""
    adopted: list[tuple[str, str | None, PackageRequirements]] = [
        (fitted.name, fitted.version, fitted.requirements) for fitted in fit.registry
    ]
    adopted.extend((fitted.name, fitted.version, fitted.requirements) for fitted in fit.local)
    found: list[Advisory] = []
    for package_name, version, requirements in adopted:
        for requirement_name, requirement_range in _library_requirements(requirements):
            if requirement_range.startswith(_WORKSPACE_RANGE_PREFIX):
                continue
            brought = view.brought_version(candidate, requirement_name)
            if brought is not None and not view.satisfies(requirement_name, brought, requirement_range):
                found.append(Advisory(package_name, version, requirement_name, requirement_range, brought))
    return tuple(found)
