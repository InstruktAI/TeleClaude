"""Replace the Resolve credentials step in release.yaml."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from tools.ci.gha import append_env, emit_error, emit_mask, required_env

ACCESS_TOKEN_KEY = "accessToken"
ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
CLAUDE_AUTH = "claudeAiOauth"
CODEX_AUTH_PATH = ".codex/auth.json"
CODEX_ERROR = "Codex credentials not found at ~/.codex/auth.json. Run: codex auth login"
CREDENTIAL_SERVICE = "Claude Code-credentials"
EMPTY_VALUE = ""
EFFECTIVE_HOME = "Effective HOME="
GITHUB_ENV = "GITHUB_ENV"
GEMINI_AUTH_PATH = ".gemini/oauth_creds.json"
GEMINI_ERROR = "Gemini credentials not found at ~/.gemini/oauth_creds.json. Run: gemini auth login"
HOME = "HOME"
HOME_ROOT = "/Users"
KEYCHAIN_ERROR = "Claude Code credentials not found in keychain. Run: claude login"
KEYCHAIN_PARSE_ERROR = "Could not extract accessToken from keychain credentials"
KEYCHAIN_SUCCESS = "Claude API key extracted from keychain"
MISSING_COUNT_SUFFIX = " CLI credential(s) missing or invalid"
RESOLVE_HOME_PREFIX = "Correcting HOME: "
RESOLVE_HOME_SEPARATOR = " -> "
SECURITY_COMMAND = "security"
SECURITY_FIND_PASSWORD = "find-generic-password"
SECURITY_PASSWORD_FLAG = "-w"
SECURITY_SERVICE_FLAG = "-s"


def corrected_home(home: str) -> str:
    """Resolve the case-preserved home directory from the local user directory."""
    home_name = Path(home).name.casefold()
    users_root = Path(HOME_ROOT)
    for candidate in users_root.iterdir():
        if candidate.is_dir() and candidate.name.casefold() == home_name:
            return str(candidate)
    return home


def keychain_credentials() -> str:
    """Read Claude credentials from the macOS keychain."""
    # macOS Keychain is the authoritative source for this runner credential.
    result = subprocess.run(
        [SECURITY_COMMAND, SECURITY_FIND_PASSWORD, SECURITY_SERVICE_FLAG, CREDENTIAL_SERVICE, SECURITY_PASSWORD_FLAG],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else EMPTY_VALUE


def access_token(credentials: str) -> str:
    """Extract the Claude OAuth access token from keychain JSON."""
    try:
        payload: object = json.loads(credentials)
        if not isinstance(payload, dict):
            return EMPTY_VALUE
        oauth = payload.get(CLAUDE_AUTH)
        if not isinstance(oauth, dict):
            return EMPTY_VALUE
        token = oauth.get(ACCESS_TOKEN_KEY)
        return token if isinstance(token, str) else EMPTY_VALUE
    except json.JSONDecodeError:
        return EMPTY_VALUE


def validate_cli_credentials(home: str) -> int:
    """Report every missing local CLI credential and return the count."""
    errors = 0
    if not (Path(home) / CODEX_AUTH_PATH).is_file():
        emit_error(CODEX_ERROR)
        errors += 1
    if not (Path(home) / GEMINI_AUTH_PATH).is_file():
        emit_error(GEMINI_ERROR)
        errors += 1
    return errors


def main(argv: list[str] | None = None) -> int:
    """Resolve and validate the release runner's CLI credentials."""
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    home = required_env(HOME)
    resolved_home = corrected_home(home)
    if resolved_home != home:
        print(RESOLVE_HOME_PREFIX + home + RESOLVE_HOME_SEPARATOR + resolved_home)
        append_env(HOME, resolved_home)
        home = resolved_home
    print(EFFECTIVE_HOME + home)
    required_env(GITHUB_ENV)
    credentials = keychain_credentials()
    if not credentials:
        emit_error(KEYCHAIN_ERROR)
        return 1
    token = access_token(credentials)
    if not token:
        emit_error(KEYCHAIN_PARSE_ERROR)
        return 1
    emit_mask(token)
    append_env(ANTHROPIC_API_KEY, token)
    print(KEYCHAIN_SUCCESS)
    errors = validate_cli_credentials(home)
    if errors:
        emit_error(str(errors) + MISSING_COUNT_SUFFIX)
        return 1
    print("All CLI credentials verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
