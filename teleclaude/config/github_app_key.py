"""Resolve a GitHub App's private key from the machine's declaration and protected environment."""

from base64 import b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass
from enum import StrEnum

import yaml
from instrukt_ai_logging import get_logger
from pydantic import SecretStr

from teleclaude.config._environment import read_environment_transaction, resolve_owner_linked_environment
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.loader import read_global_config_transaction
from teleclaude.file_transaction import file_transaction
from teleclaude.paths import GLOBAL_CONFIG_PATH, ConfigFileName
from teleclaude.types.github_binding import GitHubActorAssignment

logger = get_logger(__name__)
_UTF8 = "utf-8"
_GITHUB_KEY_REFUSED_EVENT = "github_app_key_refused app_id=%s reason=%s"


class GitHubAppKeyFailure(StrEnum):
    """Value-free prerequisite failures from protected config resolution."""

    CONFIG_UNAVAILABLE = "config_unavailable"
    PROFILE_MISSING = "profile_missing"
    ACTOR_MISMATCH = "actor_mismatch"
    KEY_UNAVAILABLE = "key_unavailable"
    KEY_MISSING = "key_missing"
    KEY_MALFORMED = "key_malformed"


class GitHubAppKeyRefused(ValueError):
    """The config owner supplies no usable key for the assigned actor."""

    def __init__(self, reason: GitHubAppKeyFailure) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GitHubAppKeyMaterial:
    """One App key in both forms the platform holds it: as stored (base64) and as decoded PEM."""

    encoded: SecretStr
    pem: SecretStr


def resolve_github_app_private_key(assignment: GitHubActorAssignment) -> SecretStr:
    """Resolve only the recorded App after authenticated admission, with no ambient fallback."""
    return resolve_github_app_key_material(assignment).pem


def resolve_github_app_key_material(assignment: GitHubActorAssignment) -> GitHubAppKeyMaterial:
    """Resolve the recorded App's key in its stored and decoded forms, with no ambient fallback."""
    try:
        with file_transaction(GLOBAL_CONFIG_PATH) as declaration_transaction:
            try:
                declaration = read_global_config_transaction(declaration_transaction)
            except (ConfigLoadError, OSError, ValueError, yaml.YAMLError):
                raise GitHubAppKeyRefused(GitHubAppKeyFailure.CONFIG_UNAVAILABLE) from None
            profile = next(
                (item for item in declaration.github.apps if item.assignment.app_id == assignment.app_id), None
            )
            if profile is None:
                raise GitHubAppKeyRefused(GitHubAppKeyFailure.PROFILE_MISSING)
            if not profile.assignment.actor.same_account(assignment.actor):
                raise GitHubAppKeyRefused(GitHubAppKeyFailure.ACTOR_MISMATCH)
            environment_path = resolve_owner_linked_environment(GLOBAL_CONFIG_PATH.with_name(ConfigFileName.ENV))
            with file_transaction(environment_path) as environment_transaction:
                try:
                    values = read_environment_transaction(environment_transaction, owner_only=True, interpolate=False)
                except (OSError, ValueError):
                    raise GitHubAppKeyRefused(GitHubAppKeyFailure.KEY_UNAVAILABLE) from None
                encoded = values.get(profile.private_key_base64_env)
                if not encoded:
                    raise GitHubAppKeyRefused(GitHubAppKeyFailure.KEY_MISSING)
                try:
                    pem = b64decode(encoded, validate=True).decode(_UTF8)
                except (Base64Error, ValueError):
                    raise GitHubAppKeyRefused(GitHubAppKeyFailure.KEY_MALFORMED) from None
                if not pem.strip():
                    raise GitHubAppKeyRefused(GitHubAppKeyFailure.KEY_MALFORMED)
                return GitHubAppKeyMaterial(encoded=SecretStr(encoded), pem=SecretStr(pem))
    except GitHubAppKeyRefused as error:
        logger.warning(_GITHUB_KEY_REFUSED_EVENT, assignment.app_id, error.reason)
        raise
    except OSError:
        logger.warning(_GITHUB_KEY_REFUSED_EVENT, assignment.app_id, GitHubAppKeyFailure.KEY_UNAVAILABLE)
        raise GitHubAppKeyRefused(GitHubAppKeyFailure.KEY_UNAVAILABLE) from None
