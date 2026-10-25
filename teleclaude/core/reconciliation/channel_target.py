"""The source an installation follows and the target its channel resolves when an install names no revision.

The source is the repository the kept repository's remote names. Edge follows the newest main revision of
that source whose required checks all passed, which integration answers under its one required-check rule;
stable follows the newest release version the source has tagged inside the compatibility series the active
release derives, or the newest tagged release when none is active. A named release tag is a published-release
target; any other reference is a mainline revision
(``local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update``).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Final

import yaml
from pydantic import ValidationError

from teleclaude.config._models import ReleaseChannel
from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.config.project_models import CiConfig
from teleclaude.core.integration.newest_green import NewestGreenStatus, newest_green_main_revision
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.deployment import parse_version
from teleclaude.deployment.migration_runner import DeploymentMigrationError, committed_version
from teleclaude.git import GitCommandError, Repo

_TAG_TEMPLATE = "v{major}.{minor}.{patch}"
_NO_GREEN = "no green main revision is known for {source}: {detail}"
_NO_SOURCE = "the installation follows no GitHub source"
_NO_RELEASE = "the source has tagged no release the {channel} channel admits"
_ACTIVE_VERSION_UNREADABLE = "the version the active release {revision} commits could not be read: {error}"
_REMOTE_NAME = "origin"
_REMOTE_PATTERN: Final = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$")
_FULL_NAME_TEMPLATE = "{owner}/{name}"
_DECLARATION_TEMPLATE = "{commit}:{path}"
_DECLARATION_PATH = "teleclaude.yml"
_CI_FIELD = "ci"
_REQUIRED_CHECKS_FIELD = "required_checks"


class ChannelTargetError(RuntimeError):
    """The channel resolves no target; the message says why."""


@dataclass(frozen=True)
class ChannelTarget:
    """A reference the channel selects and the published release it names, when it names one."""

    reference: str
    release_tag: str | None


def release_tag_of(reference: str) -> str | None:
    """The reference itself when it is a canonical release tag, else ``None``."""
    try:
        major, minor, patch = parse_version(reference)
    except ValueError:
        return None
    canonical = _TAG_TEMPLATE.format(major=major, minor=minor, patch=patch)
    return canonical if canonical == reference else None


def source_full_name(layout: InstallationLayout) -> str | None:
    """The ``owner/name`` of the repository the installation follows, or ``None`` when it keeps none or follows no GitHub remote."""
    if not layout.repository.is_dir():
        return None
    try:
        url = str(Repo(str(layout.repository)).remote(_REMOTE_NAME).url)
    except (GitCommandError, ValueError, OSError):
        return None
    matched = _REMOTE_PATTERN.search(url)
    if matched is None:
        return None
    return _FULL_NAME_TEMPLATE.format(owner=matched.group("owner"), name=matched.group("name"))


def active_release_version(layout: InstallationLayout) -> tuple[int, int, int] | None:
    """The version the active release commits, or ``None`` when nothing is active.

    The compatibility series of a stable installation is derived from it and never declared. A release whose
    version cannot be read is an error, never a guessed series.
    """
    active = layout.active_revision()
    if active is None:
        return None
    try:
        return parse_version(committed_version(Repo(str(layout.repository)), active))
    except (DeploymentMigrationError, GitCommandError, OSError, ValueError) as error:
        raise ChannelTargetError(_ACTIVE_VERSION_UNREADABLE.format(revision=active, error=error)) from error


def required_checks_at(repository: Repo, revision: str) -> tuple[str, ...]:
    """The required checks the repository declares at a revision; none when it declares none.

    A revision that carries no readable declaration, or no required check, has nothing that could be green.
    """
    try:
        declared: object = yaml.safe_load(
            str(repository.git.show(_DECLARATION_TEMPLATE.format(commit=revision, path=_DECLARATION_PATH)))
        )
    except (GitCommandError, yaml.YAMLError):
        return ()
    ci = declared.get(_CI_FIELD) if isinstance(declared, dict) else None
    checks = ci.get(_REQUIRED_CHECKS_FIELD) if isinstance(ci, dict) else None
    if not isinstance(checks, list):
        return ()
    try:
        return tuple(CiConfig(required_checks=checks).required_checks)
    except ValidationError:
        return ()


def channel_target(layout: InstallationLayout, channel: ReleaseChannel) -> ChannelTarget:
    """Resolve the target ``channel`` selects from the kept repository, which the caller has fetched."""
    if channel is ReleaseChannel.EDGE:
        return _newest_green_target(layout)
    active = active_release_version(layout)
    return newest_release_target(layout, CompatibilitySeries.of_version(active) if active is not None else None)


def _newest_green_target(layout: InstallationLayout) -> ChannelTarget:
    """The newest green main revision of the source, never the moving mainline."""
    source = source_full_name(layout)
    if source is None:
        raise ChannelTargetError(_NO_SOURCE)
    repository = Repo(str(layout.repository))
    answer = asyncio.run(
        newest_green_main_revision(
            source, lambda revision: required_checks_at(repository, revision), layout.active_revision()
        )
    )
    if answer.status is not NewestGreenStatus.GREEN or answer.revision is None:
        raise ChannelTargetError(_NO_GREEN.format(source=source, detail=answer.detail))
    return ChannelTarget(reference=answer.revision, release_tag=None)


def newest_release_target(layout: InstallationLayout, series: CompatibilitySeries | None) -> ChannelTarget:
    """The newest tagged release inside ``series``, or the newest tagged release when there is none."""
    versions = sorted(
        {
            parse_version(name)
            for name in (tag.name for tag in Repo(str(layout.repository)).tags)
            if release_tag_of(name) is not None
        }
    )
    admitted = [version for version in versions if series is None or series.admits(version)]
    if not admitted:
        raise ChannelTargetError(_NO_RELEASE.format(channel=ReleaseChannel.STABLE.value))
    major, minor, patch = admitted[-1]
    tag = _TAG_TEMPLATE.format(major=major, minor=minor, patch=patch)
    return ChannelTarget(reference=tag, release_tag=tag)
