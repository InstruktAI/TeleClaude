"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

import re
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

# API socket configuration
API_SOCKET_PATH = "/tmp/teleclaude-api.sock"
MCP_SOCKET_PATH = "/tmp/teleclaude.sock"

# Internal configuration (not user-configurable)
DATABASE_FILENAME = "teleclaude.db"
DIRECTORY_CHECK_INTERVAL = 5  # Seconds between directory change checks
OUTPUT_CADENCE_S = 1.0
HELP_DESK_SUBDIR = ".teleclaude/help-desk"
WHATSAPP_API_VERSION = "v21.0"
UI_MESSAGE_MAX_CHARS = 3900  # Char budget for content selection (format + fit)
TELEGRAM_MAX_MESSAGE_BYTES = 4096  # Telegram API hard limit for message text

# Common protocol tokens (internal canonical strings)
MAIN_MODULE = "__main__"
LOCAL_COMPUTER = "local"
ENV_ENABLE = "1"

# System roles
ROLE_ORCHESTRATOR = "orchestrator"
ROLE_WORKER = "worker"
ROLE_INTEGRATOR = "integrator"

# Human identity roles
HUMAN_ROLE_ADMIN = "admin"
HUMAN_ROLE_MEMBER = "member"
HUMAN_ROLE_CONTRIBUTOR = "contributor"
HUMAN_ROLE_NEWCOMER = "newcomer"
HUMAN_ROLE_CUSTOMER = "customer"
HUMAN_ROLES = (HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER)

ROLE_VALUES = ("public", "member", "admin")
SNIPPET_VISIBILITY_PUBLIC = "public"
SNIPPET_VISIBILITY_INTERNAL = "internal"
SNIPPET_VISIBILITY_VALUES = (SNIPPET_VISIBILITY_PUBLIC, SNIPPET_VISIBILITY_INTERNAL)


class ResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    SENT = "sent"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class ComputerStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    RESTARTING = "restarting"


class SystemCommand(str, Enum):
    HEALTH_CHECK = "health_check"
    EXIT = "exit"


class SlashCommand(str, Enum):
    """Canonical slash commands dispatched to agent sessions."""

    NEXT_BUILD = "next-build"
    NEXT_BUGS_FIX = "next-bugs-fix"
    NEXT_REVIEW_BUILD = "next-review-build"
    NEXT_REVIEW_PLAN = "next-review-plan"
    NEXT_REVIEW_REQUIREMENTS = "next-review-requirements"
    NEXT_FIX_REVIEW = "next-fix-review"
    NEXT_FINALIZE = "next-finalize"
    NEXT_PREPARE_DISCOVERY = "next-prepare-discovery"
    NEXT_PREPARE_DRAFT = "next-prepare-draft"
    NEXT_PREPARE_GATE = "next-prepare-gate"
    NEXT_PREPARE = "next-prepare"
    NEXT_WORK = "next-work"
    NEXT_INTEGRATE = "next-integrate"


class JobRole(str, Enum):
    """Canonical job roles for sessions spawned by slash commands."""

    BUILDER = "builder"
    FIXER = "fixer"
    REVIEWER = "reviewer"
    FINALIZER = "finalizer"
    DISCOVERER = "discoverer"
    DRAFTER = "drafter"
    GATE_CHECKER = "gate-checker"
    PREPARE_ORCHESTRATOR = "prepare-orchestrator"
    WORK_ORCHESTRATOR = "work-orchestrator"
    INTEGRATOR = "integrator"


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


# System message prefix — all daemon-injected messages use this prefix.
TELECLAUDE_SYSTEM_PREFIX = "[TeleClaude"


def format_system_message(label: str, content: str = "") -> str:
    """Format a daemon-injected system message with the canonical TeleClaude prefix.

    Returns ``[TeleClaude {label}]`` when no content is given, or
    ``[TeleClaude {label}]\\n\\n{content}`` when content is provided.
    """
    header = f"[TeleClaude {label}]"
    if content:
        return f"{header}\n\n{content.strip()}"
    return header


_INTERNAL_WRAPPER_RE = re.compile(
    r"^\s*<(task-notification|system-reminder)\b[^>]*>.*</\1>\s*$",
    re.DOTALL,
)


def is_internal_user_text(text: str) -> bool:
    """Return True if text is system-injected content that must not enter public data fields.

    Detects:
    - TeleClaude system prefix ("[TeleClaude ...")
    - Claude Code task-notification wrappers (full or prefix)
    - Claude Code system-reminder wrappers (full or prefix)
    """
    stripped = text.lstrip()
    if stripped.startswith(TELECLAUDE_SYSTEM_PREFIX):
        return True
    if stripped.startswith(("<task-notification", "<system-reminder")):
        return True
    if _INTERNAL_WRAPPER_RE.match(text):
        return True
    return False


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

# Worktree directory name (git worktrees live at {project}/trees/{slug})
WORKTREE_DIR = "trees"

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
        "session_root": "~/.claude/projects",
        "session_pattern": "*/*.jsonl",
        "profiles": {
            "default": ('--dangerously-skip-permissions --settings \'{"forceLoginMethod": "claudeai"}\''),
            "restricted": (
                "--strict-mcp-config"
                ' --settings \'{"forceLoginMethod": "claudeai", "enabledMcpjsonServers": []}\''
                " --add-dir ~/.teleclaude/docs"
            ),
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
        "session_root": "~/.gemini/tmp",
        "session_pattern": "*/chats/*.json",
        "profiles": {
            "default": "--yolo --allowed-mcp-server-names _none_",
            "restricted": "--sandbox --include-directories ~/.teleclaude/docs --allowed-mcp-server-names _none_",
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
        "session_root": "~/.codex/sessions",
        "session_pattern": "**/*.jsonl",
        "profiles": {
            "default": "--dangerously-bypass-approvals-and-sandbox --search",
            "restricted": "--full-auto --search",
        },
        "model_flags": {
            "fast": (
                "-m gpt-5.4"
                " --config model_reasoning_effort='medium'"
                " --config model_supports_reasoning_summaries=true"
                " --config show_raw_agent_reasoning=true"
                " --config hide_agent_reasoning=false"
            ),
            "med": (
                "-m gpt-5.4"
                " --config model_reasoning_effort='high'"
                " --config model_supports_reasoning_summaries=true"
                " --config show_raw_agent_reasoning=true"
                " --config hide_agent_reasoning=false"
            ),
            "slow": (
                "-m gpt-5.4"
                " --config model_reasoning_effort='xhigh'"
                " --config model_supports_reasoning_summaries=true"
                " --config show_raw_agent_reasoning=true"
                " --config hide_agent_reasoning=false"
            ),
        },
        "exec_subcommand": "exec",
        "interactive_flag": "",
        "non_interactive_flag": "",
        "resume_template": "{base_cmd} resume {session_id}",
        "continue_template": "{base_cmd} resume --last",
    },
}
