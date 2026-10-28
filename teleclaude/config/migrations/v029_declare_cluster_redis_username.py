"""Declare the cluster Redis user beside its URL and password, read from the machine environment."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 29
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_REDIS = "redis"
_CLUSTER = "cluster"
_USERNAME = "username"
_USERNAME_REFERENCE: Final = "${REDIS_CLUSTER_USERNAME}"


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Give a cluster block that names no user the environment reference; an unset variable leaves it unset.

    A lone computer's cluster settings name its own local Redis, which requires its ACL user, so the user has to
    reach the cluster client the same way the URL and password do. A block that already names a user, and a value
    that is not a mapping, are left as they are.
    """
    redis = document.get(_REDIS)
    if not isinstance(redis, MutableMapping):
        return
    cluster = redis.get(_CLUSTER)
    if not isinstance(cluster, MutableMapping) or _USERNAME in cluster:
        return
    cluster[_USERNAME] = _USERNAME_REFERENCE
