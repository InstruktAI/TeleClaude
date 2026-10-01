"""TeleClaude CLI package."""

from enum import StrEnum


class CommandScope(StrEnum):
    """Where a person's role is resolved for one command."""

    INVOCATION = "invocation"
    PLATFORM = "platform"
    CONFIG_SUBJECT = "config_subject"
    TARGET_SESSION = "target_session"
    TARGET_PATH = "target_path"
    NAMED_TRUSTED_DIRECTORY = "named_trusted_directory"
    NAMED_COMPANY = "named_company"


class ConfigSubjectType(StrEnum):
    """Configuration subcommands whose subject can be role-scoped."""

    PERSON = "person"
    COMPANY = "company"
    PROJECT = "project"
