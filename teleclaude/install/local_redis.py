"""TeleClaude's own local Redis on this computer (``local/projects/teleclaude/design/architecture/event-delivery``).

Every computer, the cluster host included, runs a Redis server process of TeleClaude's own: its configuration and data
live in the platform home, it listens only on a Unix socket only the TeleClaude user can open, its TCP port and default
user are off, and one ACL user's password lives in the machine environment. A unit the installation owns keeps it
running, and stopping the daemon leaves it running. It never touches another Redis on the computer.

The install act runs it in two steps. ``prepare`` runs while the previous release serves: it installs the Redis server
binary when missing and checks what the stopped window will need, and may prompt for sudo. ``apply`` runs in the
stopped window before the release's migrations: it writes the configuration and the unit, starts the instance,
verifies it and writes the variables that make the platform use it, never installing and never prompting. A computer
with no cluster Redis of its own names this local Redis as its cluster Redis. Neither step fails the install: a refusal
is logged with its reason and what resolves it, and local events stay on the cluster Redis.
"""

from __future__ import annotations

import argparse
import os
import pwd
import secrets
import shutil
import subprocess
import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger
from redis import Redis
from redis.exceptions import RedisError

from teleclaude.config._environment import read_environment_file, reconcile_environment_values, write_environment_values
from teleclaude.core.reconciliation.template_installation import render_template
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ENV_PATH, LOGS_DIR, REPO_ROOT, TELECLAUDE_HOME

logger = get_logger(__name__)


class _Variable(StrEnum):
    CLUSTER_URL = "REDIS_CLUSTER_URL"
    CLUSTER_USERNAME = "REDIS_CLUSTER_USERNAME"
    CLUSTER_PASSWORD = "REDIS_CLUSTER_PASSWORD"
    EARLIER_CLUSTER_URL = "REDIS_URL"
    LOCAL_URL = "REDIS_LOCAL_URL"
    LOCAL_USERNAME = "REDIS_LOCAL_USERNAME"
    LOCAL_PASSWORD = "REDIS_LOCAL_PASSWORD"


class _Placeholder(StrEnum):
    REDIS_SERVER = "REDIS_SERVER"
    REDIS_CONF = "REDIS_CONF"
    LOG_PATH = "LOG_PATH"
    USER = "USER"


class _Program(StrEnum):
    """The host programs this module drives; none has a Python API."""

    LAUNCHCTL = "launchctl"
    SYSTEMCTL = "systemctl"
    SUDO = "sudo"
    TEE = "tee"
    CAT = "cat"
    REMOVE = "rm"
    TRUE = "true"
    BREW = "brew"
    SERVER = "redis-server"


class _Argument(StrEnum):
    """The arguments passed to those programs."""

    SUDO_NO_PROMPT = "-n"
    REMOVE_FORCE = "-f"
    LAUNCHCTL_PRINT = "print"
    LAUNCHCTL_BOOTSTRAP = "bootstrap"
    LAUNCHCTL_BOOTOUT = "bootout"
    LAUNCHCTL_KICKSTART = "kickstart"
    LAUNCHCTL_KILL_FIRST = "-k"
    SYSTEMCTL_IS_ACTIVE = "is-active"
    SYSTEMCTL_IS_ENABLED = "is-enabled"
    SYSTEMCTL_QUIET = "--quiet"
    SYSTEMCTL_DAEMON_RELOAD = "daemon-reload"
    SYSTEMCTL_ENABLE = "enable"
    SYSTEMCTL_DISABLE = "disable"
    SYSTEMCTL_NOW = "--now"
    SYSTEMCTL_RESTART = "restart"
    SYSTEMCTL_START = "start"
    BREW_PREFIX = "--prefix"
    BREW_INSTALL = "install"
    BREW_SERVICES = "services"
    BREW_RESTART = "restart"
    BREW_FORMULA = "redis"


class _Step(StrEnum):
    """What each host command does, as a refusal names it."""

    BREW_PREFIX = "read the Homebrew prefix"
    BREW_INSTALL = "install Redis with Homebrew"
    PACKAGE_INSTALL = "install Redis"
    DISABLE_SYSTEM_SERVICE = "disable the Redis service the package started"
    UNLOAD_AGENT = "unload the local Redis agent"
    LOAD_AGENT = "load the local Redis agent"
    RESTART_AGENT = "restart the local Redis agent"
    DEPLOY_UNIT = "deploy the local Redis unit"
    RELOAD_SYSTEMD = "reload systemd"
    ENABLE_UNIT = "enable the local Redis unit"
    RESTART_UNIT = "restart the local Redis unit"
    START_UNIT = "start the local Redis unit"
    READ_SYSTEM_CONF = "read the operating system's Redis configuration"
    RESTORE_SYSTEM_CONF = "restore the operating system's Redis configuration"
    REMOVE_DROP_IN = "remove the earlier Redis drop-in"
    RESTART_SYSTEM_REDIS = "restart the operating system's Redis"
    SUDO_CHECK = "use sudo without a prompt, which the install's stopped window needs"


class LocalRedisRefused(RuntimeError):
    """The local Redis could not be set up; the message names the cause and what resolves it."""


_MACOS_PLATFORM: Final = "darwin"
_LINUX_PLATFORM_PREFIX: Final = "linux"
_NEWLINE: Final = "\n"
_USERNAME: Final = "teleclaude"
_UNIX_SCHEME: Final = "unix://"
_REDIS_DIR: Final = TELECLAUDE_HOME / "redis"
_CONF_PATH: Final = _REDIS_DIR / "local.conf"
_DATA_DIR: Final = _REDIS_DIR / "local"
_SOCKET_PATH: Final = _REDIS_DIR / "local.sock"
_LOG_PATH: Final = LOGS_DIR / "redis-local.log"
_LOCAL_URL: Final = _UNIX_SCHEME + str(_SOCKET_PATH)
_PRIVATE_DIR_MODE: Final = 0o700
_PRIVATE_FILE_MODE: Final = 0o600
_CONF_TEMPLATE: Final = (
    "# TeleClaude's own local Redis. Written by the installation; edits are replaced.\n"
    "port 0\n"
    "unixsocket {socket}\n"
    "unixsocketperm 700\n"
    "dir {data}\n"
    "appendonly yes\n"
    "appendfsync everysec\n"
    "user default off\n"
    "user {username} on >{password} ~* &* +@all\n"
)
_TEMPLATES_DIR: Final = REPO_ROOT / "templates"
_LAUNCHD_LABEL: Final = "ai.instrukt.teleclaude.redis"
_LAUNCHD_TEMPLATE: Final = _TEMPLATES_DIR / "ai.instrukt.teleclaude.redis.plist"
_LAUNCHD_PLIST: Final = Path.home() / "Library" / "LaunchAgents" / "ai.instrukt.teleclaude.redis.plist"
_LAUNCHD_DOMAIN_TEMPLATE: Final = "gui/{uid}"
_LAUNCHD_TARGET_TEMPLATE: Final = "gui/{uid}/{label}"
_SYSTEMD_SERVICE: Final = "teleclaude-redis"
_SYSTEMD_TEMPLATE: Final = _TEMPLATES_DIR / "teleclaude-redis.service"
_SYSTEMD_UNITS_DIR: Final = Path("/etc/systemd/system")
_SYSTEMD_UNIT: Final = _SYSTEMD_UNITS_DIR / "teleclaude-redis.service"
_DROP_IN_DIR_TEMPLATE: Final = "{service}.service.d"
# Homebrew's own locations, for an installing process whose PATH does not name it (a launchd-run install).
_BREW_CANDIDATES: Final = (Path("/opt/homebrew/bin/brew"), Path("/usr/local/bin/brew"))
_BREW_BIN_DIR: Final = Path("bin")
_BREW_CONF: Final = Path("etc") / "redis.conf"
_SYSTEM_BINARIES: Final = (Path("/usr/bin/redis-server"), Path("/usr/sbin/redis-server"))
_PACKAGE_COMMANDS: Final = (
    ("apt-get", ("apt-get", "install", "-y"), "redis-server"),
    ("dnf", ("dnf", "install", "-y"), "redis"),
    ("pacman", ("pacman", "-S", "--noconfirm"), "redis"),
)
# The services an operating system's Redis package may start by itself; one the install added is disabled.
_SYSTEM_SERVICES: Final = ("redis-server", "redis")
_PACKAGE_TIMEOUT_S: Final = 900
_SOCKET_WAIT_S: Final = 15.0
_SOCKET_POLL_S: Final = 0.25
_PROBE_TIMEOUT_S: Final = 2
_PASSWORD_BYTES: Final = 32
# The earlier installer configured the operating system's Redis with a marked block, a Linux drop-in, and these sockets.
_EARLIER_BLOCK_START: Final = "# >>> teleclaude local redis"
_EARLIER_BLOCK_END: Final = "# <<< teleclaude local redis"
_EARLIER_CONFS: Final = (Path("/etc/redis/redis.conf"), Path("/etc/redis.conf"))
_EARLIER_DROP_IN: Final = "teleclaude.conf"
_EARLIER_SOCKETS: Final = frozenset(
    {
        _UNIX_SCHEME + str(TELECLAUDE_HOME / "redis" / "redis.sock"),
        _UNIX_SCHEME + "/run/redis/redis-server.sock",
        _UNIX_SCHEME + "/run/redis/redis.sock",
    }
)
_PREPARE_OPTION: Final = "--prepare"
_FLAG_ACTION: Final = "store_true"
_NO_PASSWORD: Final = ""
# The machine environment holds the Redis credentials, so only its owner may read a file this creates.
_OWNER_ONLY_MODE: Final = 0o600
_PREPARED_EVENT: Final = "local_redis_prepared"
_CONFIGURED_EVENT: Final = "local_redis_configured"
_UNCHANGED_EVENT: Final = "local_redis_unchanged"
_OPERATOR_OWNED_EVENT: Final = "local_redis_operator_configured"
_PACKAGE_INSTALLED_EVENT: Final = "local_redis_package_installed"
_SYSTEM_SERVICE_DISABLED_EVENT: Final = "local_redis_system_service_disabled"
_CLUSTER_ON_LOCAL_EVENT: Final = "local_redis_named_as_cluster_redis"
_EARLIER_SETUP_RETIRED_EVENT: Final = "local_redis_earlier_setup_retired"
_EARLIER_SETUP_RETIRE_FAILED_EVENT: Final = "local_redis_earlier_setup_retire_failed"
_FALLBACK_EVENT: Final = "local_redis_refused_local_events_stay_on_cluster"
_WITHDRAWN_EVENT: Final = "local_redis_unanswering_socket_withdrawn"
_WITHDRAW_FAILED_EVENT: Final = "local_redis_socket_withdrawal_failed"
_DOOR: Final = (
    "Resolve the cause, or run a Redis of your own on a Unix socket with an ACL user and set REDIS_LOCAL_URL, "
    "REDIS_LOCAL_USERNAME and REDIS_LOCAL_PASSWORD in {env} to reach it, then install again"
)
_COMMAND_ERROR: Final = "{step} failed: {detail}. " + _DOOR
_NO_BINARY_ERROR: Final = "the Redis server binary is not installed; the install's preparation installs it. " + _DOOR
_NO_INSTALLER_ERROR: Final = "no Homebrew or supported package manager to install Redis with. " + _DOOR
_UNSUPPORTED_ERROR: Final = "no local Redis setup for platform {platform}. " + _DOOR
_UNREACHABLE_ERROR: Final = "the local Redis did not answer on {socket} with its ACL user within {seconds:g}s. " + _DOOR


def _run(step: _Step, command: list[str], *, stdin: str | None = None, timeout: float | None = None) -> str:
    # launchctl, systemctl, Homebrew and the package managers have no Python API.
    try:
        completed = subprocess.run(command, input=stdin, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise LocalRedisRefused(_COMMAND_ERROR.format(step=step, detail=detail, env=ENV_PATH)) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LocalRedisRefused(_COMMAND_ERROR.format(step=step, detail=error, env=ENV_PATH)) from error
    return completed.stdout


def _sudo(step: _Step, *command: str, interactive: bool, stdin: str | None = None, timeout: float | None = None) -> str:
    # System units and packages belong to root. Preparation from a terminal may prompt for the password;
    # anything else fails at once instead of waiting for a prompt nobody answers.
    prompt = [] if interactive and sys.stdin.isatty() else [_Argument.SUDO_NO_PROMPT]
    return _run(step, [_Program.SUDO, *prompt, *command], stdin=stdin, timeout=timeout)


def _is_macos() -> bool:
    return sys.platform == _MACOS_PLATFORM


def _is_linux() -> bool:
    return sys.platform.startswith(_LINUX_PLATFORM_PREFIX)


def _brew() -> Path | None:
    found = shutil.which(_Program.BREW)
    if found is not None:
        return Path(found)
    return next((candidate for candidate in _BREW_CANDIDATES if candidate.exists()), None)


def _brew_prefix(brew: Path) -> Path:
    return Path(_run(_Step.BREW_PREFIX, [str(brew), _Argument.BREW_PREFIX]).strip())


def _server_binary() -> Path | None:
    found = shutil.which(_Program.SERVER)
    if found is not None:
        return Path(found)
    brew = _brew()
    if brew is not None and (candidate := _brew_prefix(brew) / _BREW_BIN_DIR / _Program.SERVER).exists():
        return candidate
    return next((candidate for candidate in _SYSTEM_BINARIES if candidate.exists()), None)


def _system_service_active(service: str) -> bool:
    command = [_Program.SYSTEMCTL, _Argument.SYSTEMCTL_IS_ACTIVE, _Argument.SYSTEMCTL_QUIET, service]
    try:
        completed = subprocess.run(command, check=False, capture_output=True)
    except OSError:
        return False
    return completed.returncode == 0


def _system_service_enabled(service: str) -> bool:
    command = [_Program.SYSTEMCTL, _Argument.SYSTEMCTL_IS_ENABLED, _Argument.SYSTEMCTL_QUIET, service]
    try:
        completed = subprocess.run(command, check=False, capture_output=True)
    except OSError:
        return False
    return completed.returncode == 0


def _install_binary() -> None:
    """Install the Redis server binary; a system service the package started by itself is disabled."""
    if _is_macos():
        brew = _brew()
        if brew is None:
            raise LocalRedisRefused(_NO_INSTALLER_ERROR.format(env=ENV_PATH))
        install = [str(brew), _Argument.BREW_INSTALL, _Argument.BREW_FORMULA]
        _run(_Step.BREW_INSTALL, install, timeout=_PACKAGE_TIMEOUT_S)
        logger.info(_PACKAGE_INSTALLED_EVENT, manager=_Program.BREW)
        return
    for manager, command, package in _PACKAGE_COMMANDS:
        if shutil.which(manager) is None:
            continue
        _sudo(_Step.PACKAGE_INSTALL, *command, package, interactive=True, timeout=_PACKAGE_TIMEOUT_S)
        logger.info(_PACKAGE_INSTALLED_EVENT, manager=manager, package=package)
        for service in _SYSTEM_SERVICES:
            # A package's service that failed to start, such as on a port another server holds, is still enabled.
            if _system_service_active(service) or _system_service_enabled(service):
                disable = (_Program.SYSTEMCTL, _Argument.SYSTEMCTL_DISABLE, _Argument.SYSTEMCTL_NOW, service)
                _sudo(_Step.DISABLE_SYSTEM_SERVICE, *disable, interactive=True)
                logger.info(_SYSTEM_SERVICE_DISABLED_EVENT, service=service)
        return
    raise LocalRedisRefused(_NO_INSTALLER_ERROR.format(env=ENV_PATH))


def _answers(url: str, username: str | None, password: str) -> bool:
    client = Redis.from_url(url, username=username, password=password, socket_timeout=_PROBE_TIMEOUT_S)
    try:
        return bool(client.ping())
    except (RedisError, OSError):
        return False
    finally:
        client.close()


def _operator_configured(environment: dict[str, str]) -> bool:
    """Whether the environment names a local Redis of the operator's own, at no socket the installation manages."""
    url = environment.get(_Variable.LOCAL_URL)
    if not url or url == _LOCAL_URL or url in _EARLIER_SOCKETS:
        return False
    username = environment.get(_Variable.LOCAL_USERNAME) or None
    return _answers(url, username, environment.get(_Variable.LOCAL_PASSWORD) or _NO_PASSWORD)


def _write_private(path: Path, text: str) -> bool:
    """Write ``text`` readable by the TeleClaude user only; True when the file changed."""
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    path.chmod(_PRIVATE_FILE_MODE)
    return True


def _rendered_unit(template: Path, binary: Path) -> str:
    values: dict[str, str] = {
        _Placeholder.REDIS_SERVER: str(binary),
        _Placeholder.REDIS_CONF: str(_CONF_PATH),
        _Placeholder.LOG_PATH: str(_LOG_PATH),
        _Placeholder.USER: pwd.getpwuid(os.getuid()).pw_name,
    }
    return render_template(template.read_text(), template=template, values=values, environ={})


def _launchd_domain() -> str:
    return _LAUNCHD_DOMAIN_TEMPLATE.format(uid=os.getuid())


def _launchd_target() -> str:
    return _LAUNCHD_TARGET_TEMPLATE.format(uid=os.getuid(), label=_LAUNCHD_LABEL)


def _launchd_loaded() -> bool:
    command = [_Program.LAUNCHCTL, _Argument.LAUNCHCTL_PRINT, _launchd_target()]
    return subprocess.run(command, check=False, capture_output=True).returncode == 0


def _kickstart_launchd() -> None:
    kickstart = [_Program.LAUNCHCTL, _Argument.LAUNCHCTL_KICKSTART, _Argument.LAUNCHCTL_KILL_FIRST, _launchd_target()]
    _run(_Step.RESTART_AGENT, kickstart)


def _start_launchd(binary: Path, *, conf_changed: bool) -> bool:
    """Deploy the user agent and start or restart it as needed; True when it was (re)started."""
    _LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = _rendered_unit(_LAUNCHD_TEMPLATE, binary)
    unit_changed = not _LAUNCHD_PLIST.exists() or _LAUNCHD_PLIST.read_text() != plist
    if unit_changed:
        _LAUNCHD_PLIST.write_text(plist)
    loaded = _launchd_loaded()
    if unit_changed or not loaded:
        if loaded:
            _run(_Step.UNLOAD_AGENT, [_Program.LAUNCHCTL, _Argument.LAUNCHCTL_BOOTOUT, _launchd_target()])
        bootstrap = [_Program.LAUNCHCTL, _Argument.LAUNCHCTL_BOOTSTRAP, _launchd_domain(), str(_LAUNCHD_PLIST)]
        _run(_Step.LOAD_AGENT, bootstrap)
        return True
    if conf_changed:
        _kickstart_launchd()
        return True
    return False


def _systemctl(step: _Step, *arguments: str) -> None:
    _sudo(step, _Program.SYSTEMCTL, *arguments, interactive=False)


def _start_systemd(binary: Path, *, conf_changed: bool) -> bool:
    """Deploy the system unit and start or restart it as needed; True when it was (re)started."""
    unit = _rendered_unit(_SYSTEMD_TEMPLATE, binary)
    unit_changed = not _SYSTEMD_UNIT.exists() or _SYSTEMD_UNIT.read_text() != unit
    if unit_changed:
        _sudo(_Step.DEPLOY_UNIT, _Program.TEE, str(_SYSTEMD_UNIT), interactive=False, stdin=unit)
        _systemctl(_Step.RELOAD_SYSTEMD, _Argument.SYSTEMCTL_DAEMON_RELOAD)
    _systemctl(_Step.ENABLE_UNIT, _Argument.SYSTEMCTL_ENABLE, _SYSTEMD_SERVICE)
    if unit_changed or conf_changed:
        _systemctl(_Step.RESTART_UNIT, _Argument.SYSTEMCTL_RESTART, _SYSTEMD_SERVICE)
        return True
    _systemctl(_Step.START_UNIT, _Argument.SYSTEMCTL_START, _SYSTEMD_SERVICE)
    return False


def _restart() -> None:
    if _is_macos():
        _kickstart_launchd()
    else:
        _systemctl(_Step.RESTART_UNIT, _Argument.SYSTEMCTL_RESTART, _SYSTEMD_SERVICE)


def _await_answer(password: str) -> None:
    deadline = time.monotonic() + _SOCKET_WAIT_S
    while time.monotonic() < deadline:
        if _answers(_LOCAL_URL, _USERNAME, password):
            return
        time.sleep(_SOCKET_POLL_S)
    raise LocalRedisRefused(_UNREACHABLE_ERROR.format(socket=_SOCKET_PATH, seconds=_SOCKET_WAIT_S, env=ENV_PATH))


def _without_earlier_block(text: str) -> str | None:
    start = text.find(_EARLIER_BLOCK_START)
    end = text.find(_EARLIER_BLOCK_END)
    if start == -1 or end == -1:
        return None
    return text[:start].rstrip(_NEWLINE) + _NEWLINE + text[end + len(_EARLIER_BLOCK_END) :].lstrip(_NEWLINE)


def _retire_earlier_macos_setup() -> None:
    brew = _brew()
    if brew is None:
        return
    conf = _brew_prefix(brew) / _BREW_CONF
    if not conf.exists() or (retired := _without_earlier_block(conf.read_text())) is None:
        return
    conf.write_text(retired)
    restart = [str(brew), _Argument.BREW_SERVICES, _Argument.BREW_RESTART, _Argument.BREW_FORMULA]
    _run(_Step.RESTART_SYSTEM_REDIS, restart)
    logger.info(_EARLIER_SETUP_RETIRED_EVENT, conf=str(conf))


def _retire_earlier_linux_setup() -> None:
    for conf in _EARLIER_CONFS:
        if not conf.exists():
            continue
        try:
            text = conf.read_text()
        except PermissionError:
            # The package keeps its configuration readable by the Redis service only.
            text = _sudo(_Step.READ_SYSTEM_CONF, _Program.CAT, str(conf), interactive=False)
        if (retired := _without_earlier_block(text)) is None:
            continue
        _sudo(_Step.RESTORE_SYSTEM_CONF, _Program.TEE, str(conf), interactive=False, stdin=retired)
        for service in _SYSTEM_SERVICES:
            drop_in = _SYSTEMD_UNITS_DIR / _DROP_IN_DIR_TEMPLATE.format(service=service) / _EARLIER_DROP_IN
            if drop_in.exists():
                _sudo(_Step.REMOVE_DROP_IN, _Program.REMOVE, _Argument.REMOVE_FORCE, str(drop_in), interactive=False)
        _systemctl(_Step.RELOAD_SYSTEMD, _Argument.SYSTEMCTL_DAEMON_RELOAD)
        for service in _SYSTEM_SERVICES:
            if _system_service_active(service):
                _systemctl(_Step.RESTART_SYSTEM_REDIS, _Argument.SYSTEMCTL_RESTART, service)
        logger.info(_EARLIER_SETUP_RETIRED_EVENT, conf=str(conf))


def _has_cluster_redis(environment: dict[str, str]) -> bool:
    return bool(environment.get(_Variable.CLUSTER_URL) or environment.get(_Variable.EARLIER_CLUSTER_URL))


def _require_supported_platform() -> None:
    if not (_is_macos() or _is_linux()):
        raise LocalRedisRefused(_UNSUPPORTED_ERROR.format(platform=sys.platform, env=ENV_PATH))


def prepare() -> None:
    """While the previous release serves: install the Redis server binary when missing and check the stopped window.

    Raises ``LocalRedisRefused``; nothing it does makes the platform use the local Redis.
    """
    _require_supported_platform()
    if _operator_configured(read_environment_file(ENV_PATH)):
        logger.info(_OPERATOR_OWNED_EVENT)
        return
    if _server_binary() is None:
        _install_binary()
    if _is_linux():
        _sudo(_Step.SUDO_CHECK, _Program.TRUE, interactive=False)
    logger.info(_PREPARED_EVENT, socket=str(_SOCKET_PATH))


def apply() -> bool:
    """In the stopped window: configure, start and verify the local Redis, then write its variables.

    Installs nothing and never prompts. True when something changed; raises ``LocalRedisRefused``.
    """
    _require_supported_platform()
    environment = read_environment_file(ENV_PATH)
    if _operator_configured(environment):
        logger.info(_OPERATOR_OWNED_EVENT)
        return False
    binary = _server_binary()
    if binary is None:
        raise LocalRedisRefused(_NO_BINARY_ERROR.format(env=ENV_PATH))
    password = environment.get(_Variable.LOCAL_PASSWORD) or secrets.token_urlsafe(_PASSWORD_BYTES)
    for directory in (_REDIS_DIR, _DATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(_PRIVATE_DIR_MODE)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    conf = _CONF_TEMPLATE.format(socket=_SOCKET_PATH, data=_DATA_DIR, username=_USERNAME, password=password)
    conf_changed = _write_private(_CONF_PATH, conf)
    start = _start_launchd if _is_macos() else _start_systemd
    changed = start(binary, conf_changed=conf_changed)
    if not changed and not _answers(_LOCAL_URL, _USERNAME, password):
        _restart()
        changed = True
    _await_answer(password)
    values: dict[str, str] = {
        _Variable.LOCAL_URL: _LOCAL_URL,
        _Variable.LOCAL_USERNAME: _USERNAME,
        _Variable.LOCAL_PASSWORD: password,
    }
    if not _has_cluster_redis(environment):
        values |= {
            _Variable.CLUSTER_URL: _LOCAL_URL,
            _Variable.CLUSTER_USERNAME: _USERNAME,
            _Variable.CLUSTER_PASSWORD: password,
        }
        logger.info(_CLUSTER_ON_LOCAL_EVENT, socket=str(_SOCKET_PATH))
    write_environment_values(ENV_PATH, values, creation_mode=_OWNER_ONLY_MODE)
    try:
        _retire_earlier_macos_setup() if _is_macos() else _retire_earlier_linux_setup()
    except Exception as error:  # supervision boundary: the earlier setup's leftovers never fail the new one
        logger.warning(_EARLIER_SETUP_RETIRE_FAILED_EVENT, reason=str(error), exc_info=True)
    logger.info(_CONFIGURED_EVENT if changed else _UNCHANGED_EVENT, socket=str(_SOCKET_PATH))
    return changed


def _withdraw_unanswering_socket() -> None:
    """Stop naming a managed local socket that does not answer, so the platform starts on the cluster Redis."""
    environment = read_environment_file(ENV_PATH)
    url = environment.get(_Variable.LOCAL_URL)
    if url is None or (url != _LOCAL_URL and url not in _EARLIER_SOCKETS):
        return
    if _answers(
        url, environment.get(_Variable.LOCAL_USERNAME), environment.get(_Variable.LOCAL_PASSWORD) or _NO_PASSWORD
    ):
        return
    reconcile_environment_values(ENV_PATH, {}, frozenset({_Variable.LOCAL_URL, _Variable.LOCAL_USERNAME}))
    logger.warning(_WITHDRAWN_EVENT, socket=url)


def apply_or_fall_back() -> bool:
    """Apply the local Redis; on any failure log why and keep local events on the cluster Redis. True when applied."""
    try:
        apply()
    except Exception as error:  # supervision boundary: no cause of the local Redis may fail the install
        logger.warning(_FALLBACK_EVENT, reason=str(error), exc_info=not isinstance(error, LocalRedisRefused))
        try:
            _withdraw_unanswering_socket()
        except Exception:  # supervision boundary: the daemon still starts on the cluster Redis it reads
            logger.exception(_WITHDRAW_FAILED_EVENT)
        return False
    return True


def main(arguments: list[str] | None = None) -> int:
    """Prepare the local Redis for an install; a refusal is logged, never a failure of the install."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_PREPARE_OPTION, action=_FLAG_ACTION, required=True)
    parser.parse_args(arguments)
    try:
        prepare()
    except Exception as error:  # supervision boundary: preparation never fails the install
        logger.warning(_FALLBACK_EVENT, reason=str(error), exc_info=not isinstance(error, LocalRedisRefused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
