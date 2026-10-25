"""Release identity: whether a checkout is a release of the installation, and which tag names a commit.

Which checkouts are releases is the installation's to say (``reconciliation.installation``): a
release is a folder of the installation's releases. The imported module location, the release
channel or a detached HEAD alone identify nothing, and no project checkout is a release. A release
is created detached at its selected commit by the install act; this module answers queries about
releases and selects, detaches or normalizes nothing.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.reconciliation.installation import is_installed_release
from teleclaude.deployment import parse_version
from teleclaude.git import Repo

_TAG_TEMPLATE = "v{major}.{minor}.{patch}"
_GIT_POINTS_AT = "--points-at"


def is_release_installation(root: Path) -> bool:
    """Whether ``root`` is a release of the installation, active or not."""
    return is_installed_release(root)


def release_tag(repository: Repo, commit: str) -> str | None:
    """The highest canonical version tag naming ``commit``, or ``None`` when the commit is no release."""
    tagged: list[tuple[tuple[int, int, int], str]] = []
    for name in str(repository.git.tag(_GIT_POINTS_AT, commit)).split():
        try:
            version = parse_version(name)
        except ValueError:
            continue
        if _tag_name(version) == name:
            tagged.append((version, name))
    return max(tagged)[1] if tagged else None


def _tag_name(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    return _TAG_TEMPLATE.format(major=major, minor=minor, patch=patch)
