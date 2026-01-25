from enum import Enum


class McpMethod(str, Enum):
    INITIALIZE = "initialize"
    TOOLS_CALL = "tools/call"
    TOOLS_LIST = "tools/list"
    NOTIFICATIONS_INITIALIZED = "notifications/initialized"
