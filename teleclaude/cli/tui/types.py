"""Shared TUI types."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias


class NodeType(str, Enum):
    """Tree node type identifiers used across TUI views."""

    COMPUTER = "computer"
    PROJECT = "project"
    SESSION = "session"
    TODO = "todo"
    FILE = "file"


class FocusLevelType(str, Enum):
    """Focus stack level identifiers."""

    COMPUTER = "computer"
    PROJECT = "project"


class NotificationLevel(str, Enum):
    """Notification severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class ActivePane(str, Enum):
    """Active pane marker for session view focus."""

    NONE = "none"
    INPUT = "input"
    OUTPUT = "output"


class TodoStatus(str, Enum):
    """Todo status values used by TUI."""

    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"


class TodoFileFlag(str, Enum):
    """Todo file availability flags."""

    HAS_REQUIREMENTS = "has_requirements"
    HAS_IMPL_PLAN = "has_impl_plan"


class ThemeMode(str, Enum):
    """Theme mode identifiers."""

    DARK = "dark"
    LIGHT = "light"


@dataclass
class StickySessionInfo:
    """Sticky session state for multi-pane view."""

    session_id: str


CursesWindow: TypeAlias = curses.window
