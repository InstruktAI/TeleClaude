"""The target an installation's channel resolves when an install names no revision.

The alpha channel follows the source's mainline. Beta follows the newest release version the source has
tagged; stable the newest inside its compatibility series. A named release tag is a published-release
target; any other reference is a mainline revision
(``local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update``).
"""

from __future__ import annotations

from dataclasses import dataclass

from teleclaude.config._models import ReleaseChannel
from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.deployment import parse_version
from teleclaude.git import Repo

_MAINLINE_REFERENCE = "origin/main"
_TAG_TEMPLATE = "v{major}.{minor}.{patch}"
_NO_SERIES = "the stable channel requires a compatibility series, and this installation declares none"
_NO_RELEASE = "the source has tagged no release the {channel} channel admits"


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


def channel_target(
    layout: InstallationLayout, channel: ReleaseChannel, series: CompatibilitySeries | None
) -> ChannelTarget:
    """Resolve the target ``channel`` selects from the kept repository, which the caller has fetched."""
    if channel is ReleaseChannel.ALPHA:
        return ChannelTarget(reference=_MAINLINE_REFERENCE, release_tag=None)
    if channel is ReleaseChannel.STABLE and series is None:
        raise ChannelTargetError(_NO_SERIES)
    versions = sorted(
        {
            parse_version(name)
            for name in (tag.name for tag in Repo(str(layout.repository)).tags)
            if release_tag_of(name) is not None
        }
    )
    admitted = [version for version in versions if series is None or series.admits(version)]
    if not admitted:
        raise ChannelTargetError(_NO_RELEASE.format(channel=channel.value))
    major, minor, patch = admitted[-1]
    tag = _TAG_TEMPLATE.format(major=major, minor=minor, patch=patch)
    return ChannelTarget(reference=tag, release_tag=tag)
