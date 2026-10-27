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
_LOCAL_DECLARATION: Final[dict[str, str]] = {
    _URL: "${REDIS_LOCAL_URL}",
    _USERNAME: "${REDIS_LOCAL_USERNAME}",
    _PASSWORD: "${REDIS_LOCAL_PASSWORD}",
}


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Keep every flat Redis setting, environment references included, as the cluster Redis's.

    The local Redis is read from its own variables; a computer that sets none keeps its local events on the
    cluster Redis. A block that already names `local` or `cluster` is left as it is, and a Redis value that is
    not a mapping is left for validation to name.
    """
    redis = document.get(_REDIS)
    if redis is None:
        return
    if not isinstance(redis, MutableMapping) or _LOCAL in redis or _CLUSTER in redis:
        return
    cluster = dict(redis)
    redis.clear()
    redis[_LOCAL] = dict(_LOCAL_DECLARATION)
    redis[_CLUSTER] = cluster
