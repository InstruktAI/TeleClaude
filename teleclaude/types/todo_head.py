"""The wire contract of the publish report between the sealed commit and the daemon."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel


class TodoHeadRequestField(StrEnum):
    """The fields of a publish report body."""

    ITEM = "item"
    SHA = "sha"
    EXPECTED_TIP = "expected_tip"
    KEY = "key"
    SWAPPED = "swapped"
    CWD = "cwd"


class TodoHeadResponseField(StrEnum):
    """The fields of a publish report response."""

    STATUS = "status"
    KEY = "key"


class TodoHeadApiRoute:
    """The routes of the publish report."""

    INTENT_ROUTER_PATH: Final = "/publish-intent"
    INTENT_PATH: Final = "/todos/publish-intent"
    COMPLETION_ROUTER_PATH: Final = "/publish-complete"
    COMPLETION_PATH: Final = "/todos/publish-complete"


class TodoIntentReceipt(BaseModel):
    """The daemon's answer to a registered publish intent."""

    status: str
    key: str
