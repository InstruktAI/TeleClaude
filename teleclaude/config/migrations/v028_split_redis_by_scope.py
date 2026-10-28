"""Move the flat Redis block under `redis.cluster` and declare this computer's local Redis beside it."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 28
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_REDIS = "redis"
_LOCAL = "local"
_CLUSTER = "cluster"
_URL = "url"
_USERNAME = "username"
_PASSWORD = "password"
_RENAMED_REFERENCES: Final[dict[str, str]] = {
    "${REDIS_URL}": "${REDIS_CLUSTER_URL}",
    "${REDIS_PASSWORD}": "${REDIS_CLUSTER_PASSWORD}",
}
_LOCAL_DECLARATION: Final[dict[str, str]] = {
    _URL: "${REDIS_LOCAL_URL}",
    _USERNAME: "${REDIS_LOCAL_USERNAME}",
    _PASSWORD: "${REDIS_LOCAL_PASSWORD}",
}


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Keep every flat Redis setting as the cluster Redis's, its environment references under the cluster names.

    The installation's environment stage gives `REDIS_CLUSTER_URL` and `REDIS_CLUSTER_PASSWORD` the values of the
    earlier names before this step runs. The local Redis is read from its own variables. A block that already
    names `local` or `cluster` is left as it is, and a Redis value that is not a mapping is left for validation.
    """
    redis = document.get(_REDIS)
    if redis is None:
        return
    if not isinstance(redis, MutableMapping) or _LOCAL in redis or _CLUSTER in redis:
        return
    cluster = {
        key: _RENAMED_REFERENCES.get(value, value) if isinstance(value, str) else value for key, value in redis.items()
    }
    redis.clear()
    redis[_LOCAL] = dict(_LOCAL_DECLARATION)
    redis[_CLUSTER] = cluster
