"""Constants used across TeleClaude.

This module defines shared constants to ensure consistency.
"""

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

# Agent metadata (NOT user-configurable)
# CLI dicts contain mixed types: str, bool, list[str], dict[str, str]
AgentCliDict = dict[str, str | bool | list[str] | dict[str, str]]
AgentDict = dict[str, str | dict[str, str] | AgentCliDict]
AGENT_METADATA: dict[str, AgentDict] = {
    "claude": {
        "session_dir": "~/.claude/sessions",
        "log_pattern": "*.jsonl",
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
        "cli": {
            "base_cmd": [
                'claude --dangerously-skip-permissions --no-session-persistence --no-chrome --tools default --settings \'{"forceLoginMethod": "claudeai", "enabledMcpjsonServers": [], "disableAllHooks": true}\''
            ],
            "output_format": "--output-format json",
            "schema_arg": "--json-schema",
            "prompt_flag": True,
            "response_field": "result",
            "response_field_type": "string_json",
            "tools_arg": "--allowed-tools",
            "mcp_tools_arg": "",
            "tools_map": {
                "web_search": "web_search",
            },
        },
    },
    "gemini": {
        "session_dir": "~/.gemini/tmp",
        "log_pattern": "**/chats/*.json",
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
        "cli": {
            "base_cmd": ["gemini --yolo --allowed-mcp-server-names=[]"],
            "output_format": "-o json",
            "schema_arg": "",
            "prompt_flag": True,
            "response_field": "response",
            "response_field_type": "string_json",
            "tools_arg": "--allowed-tools",
            "mcp_tools_arg": "--allowed-mcp-server-names",
            "tools_map": {
                "web_search": "google_web_search",
            },
        },
    },
    "codex": {
        "session_dir": "~/.codex/sessions",
        "log_pattern": "*.jsonl",
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
        "cli": {
            "base_cmd": ["codex --dangerously-bypass-approvals-and-sandbox --search"],
            "output_format": "",
            "schema_arg": "--output-schema",
            "schema_file": "true",
            "prompt_flag": False,
            "response_field": "",
            "response_field_type": "object",
            "tools_arg": "",
            "mcp_tools_arg": "",
            "tools_map": {
                "web_search": "web_search",
            },
        },
    },
}
