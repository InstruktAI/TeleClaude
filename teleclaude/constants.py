"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

from dataclasses import dataclass, field
from enum import Enum

# Taxonomy Types (single source of truth)
# Used for snippet categorization and get_context filtering
TAXONOMY_TYPES = ["principle", "concept", "policy", "procedure", "design", "spec"]

# Display suffix mapping for snippet types
TYPE_SUFFIX = {
    "policy": "Policy",
    "procedure": "Procedure",
    "principle": "Principle",
    "concept": "Concept",
    "design": "Design",
    "spec": "Spec",
}

# MCP Configuration
MCP_SOCKET_PATH = "/tmp/teleclaude.sock"
API_SOCKET_PATH = "/tmp/teleclaude-api.sock"

# Internal configuration (not user-configurable)
DIRECTORY_CHECK_INTERVAL = 5  # Seconds between directory change checks
UI_MESSAGE_MAX_CHARS = 3900  # Char budget for content selection (format + fit)
TELEGRAM_MAX_MESSAGE_BYTES = 4096  # Telegram API hard limit for message text

# Common protocol tokens (internal canonical strings)
MAIN_MODULE = "__main__"
LOCAL_COMPUTER = "local"
ENV_ENABLE = "1"

# MCP roles
ROLE_ORCHESTRATOR = "orchestrator"
ROLE_WORKER = "worker"

# Human identity roles
HUMAN_ROLE_ADMIN = "admin"
HUMAN_ROLE_MEMBER = "member"
HUMAN_ROLE_CONTRIBUTOR = "contributor"
HUMAN_ROLE_NEWCOMER = "newcomer"
HUMAN_ROLES = (HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER)


class ResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SENT = "sent"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    DEPLOYED = "deployed"


class ComputerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    RESTARTING = "restarting"


class SystemCommand(str, Enum):
    DEPLOY = "deploy"
    HEALTH_CHECK = "health_check"
    EXIT = "exit"


class Platform(str, Enum):
    DARWIN = "darwin"


# Redis payload message types
REDIS_MSG_SYSTEM = "system"

# Redis event types
EVENT_NEW_SESSION = "new_session"

# Output stream markers
OUTPUT_COMPLETE_MARKER = "[Output Complete]"
OUTPUT_SYSTEM_PREFIX = "["
OUTPUT_HOURGLASS_MARKER = "⏳"
# File suffixes
# (Boundary formats keep literals at parse sites.)

# JSON field names (internal normalized schema)
FIELD_KIND = "kind"
FIELD_ADAPTER_METADATA = "adapter_metadata"
FIELD_COMPUTER = "computer"
FIELD_COMMAND = "command"


# Checkpoint injection
CHECKPOINT_PREFIX = "[TeleClaude Checkpoint] - "
CHECKPOINT_MESSAGE = (
    f"{CHECKPOINT_PREFIX}Continue or validate your work if needed. "
    "Perform checkpoint housekeeping silently, then send a short user-relevant debrief without mentioning checkpoint chores. "
    "Any truly interesting memories to be created that meet our criteria? "
    "(DON'T abuse it as work log!) If everything that is expected of you is done, do not respond."
)

# Max chars to capture from tool result content for error enrichment
CHECKPOINT_RESULT_SNIPPET_MAX_CHARS = 500
# Threshold for wide blast radius observation
CHECKPOINT_BLAST_RADIUS_THRESHOLD = 3


@dataclass(frozen=True)
class FileCategory:
    """Maps file patterns to checkpoint action instructions."""

    name: str
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    instruction: str = ""
    evidence_substrings: list[str] = field(default_factory=list)
    evidence_must_follow_last_mutation: bool = False
    precedence: int = 0  # Lower = earlier in required actions


# File categories ordered by action precedence (R2, R9).
# Evidence substrings are matched against Bash tool call commands (R4).
CHECKPOINT_FILE_CATEGORIES: list[FileCategory] = [
    FileCategory(
        name="telec setup",
        include_patterns=[
            "teleclaude/project_setup/**",
            "templates/ai.instrukt.teleclaude.docs-watch.plist",
            "templates/teleclaude-docs-watch.service",
            "templates/teleclaude-docs-watch.path",
            ".pre-commit-config.yaml",
            ".gitattributes",
            ".husky/pre-commit",
        ],
        instruction="Run `telec init` (setup changed: watchers, hook installers, or git filters)",
        evidence_substrings=["telec init"],
        precedence=10,
    ),
    FileCategory(
        name="dependencies",
        include_patterns=["pyproject.toml", "requirements*.txt"],
        instruction="Install updated dependencies: `uv sync --extra test`",
        evidence_substrings=["uv sync", "make install", "pip install"],
        precedence=20,
    ),
    FileCategory(
        name="daemon code",
        include_patterns=["teleclaude/**/*.py"],
        exclude_patterns=["teleclaude/hooks/**", "teleclaude/cli/tui/**", "teleclaude/utils/**"],
        instruction="Run `make restart` then `make status`",
        evidence_substrings=["make restart"],
        precedence=30,
    ),
    FileCategory(
        name="shared utilities",
        include_patterns=["teleclaude/utils/**"],
        instruction="",  # Used by both daemon and hooks; agent decides if restart is needed
        evidence_substrings=[],
        precedence=35,
    ),
    FileCategory(
        name="config",
        include_patterns=["config.yml"],
        instruction="Run `make restart` then `make status`",
        evidence_substrings=["make restart"],
        precedence=30,
    ),
    FileCategory(
        name="TUI code",
        include_patterns=["teleclaude/cli/tui/**"],
        instruction="Run `pkill -SIGUSR2 -f -- '-m teleclaude.cli.telec$'`",
        evidence_substrings=["pkill -SIGUSR2", "kill -USR2"],
        evidence_must_follow_last_mutation=True,
        precedence=40,
    ),
    FileCategory(
        name="agent artifacts",
        include_patterns=["agents/**", ".agents/**", "**/AGENTS.master.md"],
        instruction=(
            "Reload artifacts: `curl -s --unix-socket "
            "/tmp/teleclaude-api.sock -X POST "
            '"http://localhost/sessions/$(cat \\"$TMPDIR/teleclaude_session_id\\")/agent-restart"`'
        ),
        # Evidence accepts direct API call text and daemon restart log markers.
        evidence_substrings=["--unix-socket /tmp/teleclaude-api.sock", "/agent-restart", "agent_restart"],
        precedence=50,
    ),
    FileCategory(
        name="hook runtime",
        include_patterns=["teleclaude/hooks/**"],
        instruction="",  # Auto-applies on next hook invocation
        evidence_substrings=[],
        precedence=100,
    ),
    FileCategory(
        name="tests only",
        include_patterns=["tests/**/*.py"],
        instruction="Run targeted tests for changed test files",
        evidence_substrings=["pytest", "make test"],
        precedence=60,
    ),
]

# Patterns for docs/non-code files (capture-only, no action required)
CHECKPOINT_NO_ACTION_PATTERNS: list[str] = [
    "docs/**",
    "todos/**",
    "ideas/**",
    "*.md",
    "*.txt",
    "*.rst",
]

# Evidence patterns for general verification actions (R4)
CHECKPOINT_STATUS_EVIDENCE = ["make status"]
CHECKPOINT_TEST_EVIDENCE = ["pytest", "make test"]
CHECKPOINT_LOG_CHECK_EVIDENCE = ["instrukt-ai-logs"]

# Error enrichment patterns (R5 Layer 2)
CHECKPOINT_ERROR_ENRICHMENT: list[tuple[str, str]] = [
    ("Traceback (most recent call last)", "Python errors remain unresolved — verify they are fixed"),
    ("SyntaxError", "Syntax errors remain — verify the code is valid"),
    ("ImportError", "Import errors remain — check dependencies or module paths"),
    ("ModuleNotFoundError", "Import errors remain — check dependencies or module paths"),
]
CHECKPOINT_TEST_ERROR_COMMANDS = ["pytest", "make test"]
CHECKPOINT_TEST_ERROR_MESSAGE = "Test failures remain — re-run tests after fixes"
CHECKPOINT_GENERIC_ERROR_MESSAGE = "A command returned errors — verify the issue is resolved"

# Misc markers / defaults
RELATIVE_CURRENT = "."
TC_WORKDIR = "TC WORKDIR"
DB_IN_MEMORY = ":memory:"

# Fallback labels
LABEL_TOOL = "tool"

# Markdown tokens
MARKDOWN_FENCE = "```"
MARKDOWN_INLINE_CODE = "`"


# Cache/event names
class CacheEvent(str, Enum):
    SESSION_STARTED = "session_started"
    SESSION_UPDATED = "session_updated"
    SESSION_CLOSED = "session_closed"
    PROJECTS_SNAPSHOT = "projects_snapshot"
    TODOS_SNAPSHOT = "todos_snapshot"
    PROJECTS_INITIAL = "projects_initial"
    PREPARATION_INITIAL = "preparation_initial"
    COMPUTER_UPDATED = "computer_updated"
    PROJECTS_UPDATED = "projects_updated"
    PROJECT_UPDATED = "project_updated"
    TODOS_UPDATED = "todos_updated"
    TODO_CREATED = "todo_created"
    TODO_UPDATED = "todo_updated"
    TODO_REMOVED = "todo_removed"


# Cache key separator
CACHE_KEY_SEPARATOR = ":"

# Cache data types
DATA_TYPE_SESSIONS = "sessions"
DATA_TYPE_TODOS = "todos"
DATA_TYPE_PROJECTS = "projects"
DATA_TYPE_PREPARATION = "preparation"


# WebSocket subscription keys
class WsAction(str, Enum):
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class AdapterKey(str, Enum):
    API = "api"


class AdapterOp(str, Enum):
    DELETE_MESSAGE = "delete_message"


class UiScope(str, Enum):
    ALL = "all_ui"


# Redis internal settings
REDIS_MAX_CONNECTIONS = 50
REDIS_SOCKET_TIMEOUT = 60  # Increased to accommodate poor network conditions
REDIS_MESSAGE_STREAM_MAXLEN = 10000  # Max messages to keep per computer
REDIS_OUTPUT_STREAM_MAXLEN = 10000  # Max output messages per session
REDIS_OUTPUT_STREAM_TTL = 3600  # Auto-expire output streams after 1 hour
REDIS_REFRESH_COOLDOWN_SECONDS = 30  # Minimum time between remote refreshes per peer+data type

# Agent protocol (NOT user-configurable)
# Fixed interface contracts for each agent CLI binary.
# The only user-configurable field is `binary` in config.yml (wrapper path).
AgentProtocolDict = dict[str, str | dict[str, str]]
AGENT_PROTOCOL: dict[str, AgentProtocolDict] = {
    "claude": {
        "session_dir": "~/.claude/sessions",
        "log_pattern": "*.jsonl",
        "profiles": {
            "default": '--dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\'',
            "restricted": '--settings \'{"forceLoginMethod": "claudeai"}\' --add-dir ~/.teleclaude/docs',
        },
        "model_flags": {
            "fast": "--model haiku",
            "med": "--model sonnet",
            "slow": "--model opus",
        },
        "exec_subcommand": "",
        "interactive_flag": "",
        "non_interactive_flag": "-p",
        "resume_template": "{base_cmd} --resume {session_id}",
        "continue_template": "{base_cmd} --continue",
    },
    "gemini": {
        "session_dir": "~/.gemini/tmp",
        "log_pattern": "**/chats/*.json",
        "profiles": {
            "default": "--yolo",
            "restricted": "--sandbox --include-directories ~/.teleclaude/docs",
        },
        "model_flags": {
            "fast": "-m gemini-2.5-flash-lite",
            "med": "-m gemini-3-flash-preview",
            "slow": "-m gemini-3-pro-preview",
        },
        "exec_subcommand": "",
        "interactive_flag": "-i",
        "non_interactive_flag": "-p",
        "resume_template": "{base_cmd} --resume {session_id}",
        "continue_template": "{base_cmd} --resume latest",
    },
    "codex": {
        "session_dir": "~/.codex/sessions",
        "log_pattern": "*.jsonl",
        "profiles": {
            "default": "--dangerously-bypass-approvals-and-sandbox --search",
            "restricted": "--full-auto --search",
        },
        "model_flags": {
            "fast": "-m gpt-5.3-codex --config model_reasoning_effort='low'",
            "med": "-m gpt-5.3-codex --config model_reasoning_effort='medium'",
            "slow": "-m gpt-5.3-codex --config model_reasoning_effort='high'",
            "deep": "-m gpt-5.3-codex --config model_reasoning_effort='xhigh'",
        },
        "exec_subcommand": "exec",
        "interactive_flag": "",
        "non_interactive_flag": "",
        "resume_template": "{base_cmd} resume {session_id}",
        "continue_template": "{base_cmd} resume --last",
    },
}
