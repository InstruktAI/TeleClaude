"""The wire contract of the sealed act command between the CLI and the daemon."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class TodoActRequestField(StrEnum):
    """The fields of an act request body."""

    ITEM = "item"
    ACT = "act"
    TEXT = "text"
    SHA = "sha"
    REVISION = "revision"
    PERSON = "person"
    FINDING = "finding"
    WAIT = "wait"
    CWD = "cwd"
    CLIENT_REQUEST_ID = "client_request_id"


class TodoActResponseField(StrEnum):
    """The fields of an act response."""

    STATUS = "status"
    ACT_KEY = "act_key"
    PHASE = "phase"
    COMPLETE = "complete"
    FINDING_KEY = "finding_key"


class TodoActApiRoute:
    """The route of the act command."""

    ROUTER_PATH: Final = "/act"
    PATH: Final = "/todos/act"


class TodoStampApiRoute:
    """The route of the stamp submission."""

    ROUTER_PATH: Final = "/act-stamp"
    PATH: Final = "/todos/act-stamp"


class TodoChildApiRoute:
    """The route of the child command."""

    ROUTER_PATH: Final = "/child"
    PATH: Final = "/todos/child"
