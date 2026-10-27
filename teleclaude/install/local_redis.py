"""Set up this computer's local Redis for its local events (``local/projects/teleclaude/design/architecture/event-delivery``).

A computer whose cluster Redis is on another computer runs the operating system's Redis as its local Redis: on a
Unix socket only its user and the Redis service can open, with the TCP port off, the default user off and one ACL user
whose password lives in the machine environment. On Linux the Redis service runs with the TeleClaude user's primary
group, so every process of that user can open the socket at once, sessions already running included.

Nothing is set up where the cluster Redis is on this computer, since it already keeps local events local, or where
the environment names a local Redis of the operator's own that answers. A Redis that another program uses or that
someone else configured is never taken over: setup refuses and names the variables that point TeleClaude at a
dedicated instance instead. Running it again changes nothing that is already in place.

The install act runs it before the release's migrations (``teleclaude.install.migrate_release``), so a refusal leaves
the previous release serving and no process of the new release runs before the local Redis is in place.
"""

from __future__ import annotations

import grp
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlparse

from instrukt_ai_logging import get_logger
from redis import Redis
from redis.exceptions import AuthenticationError, RedisError, ResponseError

from teleclaude.config._environment import read_environment_file, write_environment_values
from teleclaude.paths import ENV_PATH, TELECLAUDE_HOME

logger = get_logger(__name__)


class _Variable(StrEnum):
    CLUSTER_URL = "REDIS_CLUSTER_URL"
    EARLIER_CLUSTER_URL = "REDIS_URL"
    LOCAL_URL = "REDIS_LOCAL_URL"
    LOCAL_USERNAME = "REDIS_LOCAL_USERNAME"
    LOCAL_PASSWORD = "REDIS_LOCAL_PASSWORD"


class LocalRedisRefused(RuntimeError):
    """The local Redis could not be set up; the message names the cause and what resolves it."""


@dataclass(frozen=True)
class _LinuxLayout:
    """How one distribution family packages Redis: its package, service, configuration and runtime socket."""

    package: str
    service: str
    conf: Path
    socket: Path


@dataclass(frozen=True)
class _Platform:
    """Where this computer's Redis keeps its configuration and socket, and how it is restarted."""

    conf: Path
    socket: Path
    socket_mode: str
    brew: Path | None
    service: str | None

    @property
    def privileged(self) -> bool:
        """Whether the configuration and service belong to root (Linux) rather than the user (Homebrew)."""
        return self.brew is None


_USERNAME: Final = "teleclaude"
_UNIX_SCHEME: Final = "unix://"
_BLOCK_START: Final = "# >>> teleclaude local redis"
_BLOCK_END: Final = "# <<< teleclaude local redis"
_SOCKET_WAIT_S: Final = 15.0
_SOCKET_POLL_S: Final = 0.25
_PROBE_TIMEOUT_S: Final = 2
_PASSWORD_BYTES: Final = 32
_PACKAGE_TIMEOUT_S: Final = 900
_SERVER_BINARY: Final = "redis-server"
_MACOS_SOCKET: Final = TELECLAUDE_HOME / "redis" / "redis.sock"
_MACOS_SOCKET_MODE: Final = "700"
_MACOS_CONF: Final = Path("etc") / "redis.conf"
_BREW: Final = "brew"
# Homebrew's own locations, for an installing process whose PATH does not name it (a launchd-run install).
_BREW_CANDIDATES: Final = (Path("/opt/homebrew/bin/brew"), Path("/usr/local/bin/brew"))
_LINUX_SOCKET_MODE: Final = "770"
_LINUX_LAYOUTS: Final = (
    # Debian, Ubuntu, Raspberry Pi OS.
    _LinuxLayout("redis-server", "redis-server", Path("/etc/redis/redis.conf"), Path("/run/redis/redis-server.sock")),
    # Fedora, RHEL, Arch.
    _LinuxLayout("redis", "redis", Path("/etc/redis/redis.conf"), Path("/run/redis/redis.sock")),
    _LinuxLayout("redis", "redis", Path("/etc/redis.conf"), Path("/run/redis/redis.sock")),
)
_DEBIAN_PACKAGE: Final = "redis-server"
_OTHER_PACKAGE: Final = "redis"
_PACKAGE_COMMANDS: Final = (
    ("apt-get", ("apt-get", "install", "-y"), _DEBIAN_PACKAGE),
    ("dnf", ("dnf", "install", "-y"), _OTHER_PACKAGE),
    ("pacman", ("pacman", "-S", "--noconfirm"), _OTHER_PACKAGE),
)
_MANAGED_SOCKETS: Final = frozenset(
    {_UNIX_SCHEME + str(_MACOS_SOCKET), *(_UNIX_SCHEME + str(layout.socket) for layout in _LINUX_LAYOUTS)}
)
_SYSTEMD_UNITS: Final = Path("/etc/systemd/system")
_DROP_IN_NAME: Final = "teleclaude.conf"
_DROP_IN_TEMPLATE: Final = (
    "# TeleClaude: the local Redis socket belongs to the TeleClaude user's group.\n[Service]\nGroup={group}\n"
)
_BLOCK_TEMPLATE: Final = (
    "{start}\n"
    "port 0\n"
    "unixsocket {socket}\n"
    "unixsocketperm {mode}\n"
    "user default off\n"
    "user {username} on >{password} ~* &* +@all\n"
    "{end}\n"
)
_PORT_DIRECTIVE: Final = "port"
_DEFAULT_PORT: Final = 6379
# Directives that say someone configured this Redis for socket or authenticated access of their own.
_CONFIGURED_DIRECTIVES: Final = frozenset({"unixsocket", "requirepass", "user", "aclfile"})
_COMMENT: Final = "#"
_LOOPBACK_ADDRESS: Final = "127.0.0.1"
_CLIENTS_SECTION: Final = "clients"
_CONNECTED_CLIENTS: Final = "connected_clients"
_NOAUTH_PREFIX: Final = "NOAUTH"
_SKIPPED_EVENT: Final = "local_redis_skipped_cluster_on_this_computer"
_OPERATOR_OWNED_EVENT: Final = "local_redis_operator_configured"
_CONFIGURED_EVENT: Final = "local_redis_configured"
_UNCHANGED_EVENT: Final = "local_redis_unchanged"
_PACKAGE_INSTALLED_EVENT: Final = "local_redis_package_installed"
_DOOR: Final = (
    "Run a dedicated Redis on a Unix socket with an ACL user and set REDIS_LOCAL_URL, REDIS_LOCAL_USERNAME and "
    "REDIS_LOCAL_PASSWORD in {env} to reach it, or resolve the cause, then install again"
)
_UNREACHABLE_ERROR: Final = "the local Redis did not answer on {socket} with its ACL user within {seconds:g}s. " + _DOOR
_UNSUPPORTED_ERROR: Final = "no known Redis layout on this computer ({detail}). " + _DOOR
_IN_USE_ERROR: Final = (
    "the Redis configured in {conf} is in use by another program or was configured by someone else ({reason}); "
    "TeleClaude does not take it over. " + _DOOR
)
_COMMAND_ERROR: Final = "{step} failed: {detail}. " + _DOOR
_OTHER_CLIENTS_REASON: Final = "{count} other connected clients"
_AUTH_REASON: Final = "it requires authentication TeleClaude was not given"
_DIRECTIVE_REASON: Final = "it already sets {directive}"
_NO_BREW: Final = "Homebrew is not installed"
_NO_PACKAGE_MANAGER: Final = "no supported package manager to install Redis with"
_NO_LAYOUT: Final = "the installed Redis matches none of the known configuration and service locations"
_NO_PLATFORM: Final = "platform {platform}"


def _run(step: str, command: list[str], *, stdin: str | None = None, timeout: float | None = None) -> str:
    try:
        completed = subprocess.run(command, input=stdin, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise LocalRedisRefused(_COMMAND_ERROR.format(step=step, detail=detail, env=ENV_PATH)) from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LocalRedisRefused(_COMMAND_ERROR.format(step=step, detail=error, env=ENV_PATH)) from error
    return completed.stdout


def _sudo(step: str, *command: str, stdin: str | None = None, timeout: float | None = None) -> str:
    # The system Redis configuration and service belong to root. An interactive install may prompt for the
    # password; an unattended one fails at once instead of waiting for a prompt nobody answers.
    prefix = ["sudo"] if sys.stdin.isatty() else ["sudo", "-n"]
    return _run(step, [*prefix, *command], stdin=stdin, timeout=timeout)


def cluster_is_on_this_computer(cluster_url: str | None) -> bool:
    """Whether the cluster Redis URL names this computer: by a socket, or by an address this computer holds."""
    if not cluster_url:
        return True
    host = urlparse(cluster_url).hostname
    if not host:
        return True
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    for family, kind, _protocol, _name, address in addresses:
        # An address this computer can bind is one of its own.
        with socket.socket(family, kind) as probe:
            try:
                probe.bind((address[0], 0))
            except OSError:
                continue
            return True
    return False


def _brew() -> Path | None:
    found = shutil.which(_BREW)
    if found is not None:
        return Path(found)
    return next((candidate for candidate in _BREW_CANDIDATES if candidate.exists()), None)


def _macos_platform() -> _Platform:
    brew = _brew()
    if brew is None:
        raise LocalRedisRefused(_UNSUPPORTED_ERROR.format(detail=_NO_BREW, env=ENV_PATH))
    # Homebrew names its prefix, installs Redis and serves it; none of that has a Python API.
    prefix = Path(_run("read the Homebrew prefix", [str(brew), "--prefix"]).strip())
    if not (prefix / "bin" / _SERVER_BINARY).exists():
        _run("install Redis with Homebrew", [str(brew), "install", "redis"], timeout=_PACKAGE_TIMEOUT_S)
        logger.info(_PACKAGE_INSTALLED_EVENT, manager=_BREW)
    return _Platform(prefix / _MACOS_CONF, _MACOS_SOCKET, _MACOS_SOCKET_MODE, brew, None)


def _known_service(service: str) -> bool:
    # systemd answers whether it knows a unit; it has no Python API.
    try:
        completed = subprocess.run(["systemctl", "cat", f"{service}.service"], capture_output=True, check=False)
    except OSError:
        return False
    return completed.returncode == 0


def _installed_layout() -> _LinuxLayout | None:
    return next((layout for layout in _LINUX_LAYOUTS if layout.conf.exists() and _known_service(layout.service)), None)


def _install_linux_package() -> None:
    for manager, command, package in _PACKAGE_COMMANDS:
        if shutil.which(manager) is None:
            continue
        _sudo("install Redis", *command, package, timeout=_PACKAGE_TIMEOUT_S)
        logger.info(_PACKAGE_INSTALLED_EVENT, manager=manager, package=package)
        return
    raise LocalRedisRefused(_UNSUPPORTED_ERROR.format(detail=_NO_PACKAGE_MANAGER, env=ENV_PATH))


def _linux_platform() -> _Platform:
    layout = _installed_layout()
    if layout is None:
        _install_linux_package()
        layout = _installed_layout()
    if layout is None:
        raise LocalRedisRefused(_UNSUPPORTED_ERROR.format(detail=_NO_LAYOUT, env=ENV_PATH))
    return _Platform(layout.conf, layout.socket, _LINUX_SOCKET_MODE, None, layout.service)


def _platform() -> _Platform:
    if sys.platform == "darwin":
        return _macos_platform()
    if sys.platform.startswith("linux"):
        return _linux_platform()
    raise LocalRedisRefused(_UNSUPPORTED_ERROR.format(detail=_NO_PLATFORM.format(platform=sys.platform), env=ENV_PATH))


def _block(platform: _Platform, password: str) -> str:
    return _BLOCK_TEMPLATE.format(
        start=_BLOCK_START,
        socket=platform.socket,
        mode=platform.socket_mode,
        username=_USERNAME,
        password=password,
        end=_BLOCK_END,
    )


def _with_block(conf_text: str, block: str) -> str:
    """The configuration with this module's block replaced, or appended when it is absent."""
    start = conf_text.find(_BLOCK_START)
    end = conf_text.find(_BLOCK_END)
    if start != -1 and end != -1:
        return conf_text[:start] + block + conf_text[end + len(_BLOCK_END) :].lstrip("\n")
    return conf_text.rstrip("\n") + "\n\n" + block


def _read_conf(platform: _Platform) -> str:
    try:
        return platform.conf.read_text()
    except PermissionError:
        if not platform.privileged:
            raise
        return _sudo("read the Redis configuration", "cat", str(platform.conf))


def _write_conf(platform: _Platform, text: str) -> None:
    if platform.privileged:
        _sudo("write the Redis configuration", "tee", str(platform.conf), stdin=text)
    else:
        platform.conf.write_text(text)


def _drop_in_path(platform: _Platform) -> Path:
    return _SYSTEMD_UNITS / f"{platform.service}.service.d" / _DROP_IN_NAME


def _drop_in() -> str:
    return _DROP_IN_TEMPLATE.format(group=grp.getgrgid(os.getgid()).gr_name)


def _drop_in_current(platform: _Platform) -> bool:
    try:
        return _drop_in_path(platform).read_text() == _drop_in()
    except OSError:
        return False


def _restart(platform: _Platform) -> None:
    if platform.brew is not None:
        _run("restart Redis with Homebrew", [str(platform.brew), "services", "restart", "redis"])
        return
    service = str(platform.service)
    drop_in = _drop_in_path(platform)
    if not _drop_in_current(platform):
        _sudo("create the Redis service drop-in directory", "mkdir", "-p", str(drop_in.parent))
        _sudo("write the Redis service drop-in", "tee", str(drop_in), stdin=_drop_in())
        _sudo("reload systemd", "systemctl", "daemon-reload")
    _sudo("enable the Redis service", "systemctl", "enable", service)
    _sudo("restart the Redis service", "systemctl", "restart", service)


def _active_directives(conf_text: str) -> list[list[str]]:
    lines = (line.split() for line in conf_text.splitlines())
    return [parts for parts in lines if parts and not parts[0].startswith(_COMMENT)]


def _configured_port(directives: list[list[str]]) -> int:
    """The TCP port the configuration ends up with; Redis takes the last directive."""
    port = _DEFAULT_PORT
    for parts in directives:
        if len(parts) == 2 and parts[0] == _PORT_DIRECTIVE and parts[1].isdigit():
            port = int(parts[1])
    return port


def _refuse_if_taken(platform: _Platform, conf_text: str) -> None:
    """Refuse a Redis this module never configured that someone else configured or another program uses."""
    directives = _active_directives(conf_text)
    configured = next((parts[0] for parts in directives if parts[0] in _CONFIGURED_DIRECTIVES), None)
    if configured is not None:
        reason = _DIRECTIVE_REASON.format(directive=configured)
        raise LocalRedisRefused(_IN_USE_ERROR.format(conf=platform.conf, reason=reason, env=ENV_PATH))
    port = _configured_port(directives)
    if port == 0:
        return
    client = Redis(host=_LOOPBACK_ADDRESS, port=port, socket_timeout=_PROBE_TIMEOUT_S)
    try:
        # The synchronous client returns the parsed section; its stubs also admit the asynchronous result.
        clients = int(cast("dict[str, int]", client.info(_CLIENTS_SECTION))[_CONNECTED_CLIENTS])
    except AuthenticationError:
        raise LocalRedisRefused(_IN_USE_ERROR.format(conf=platform.conf, reason=_AUTH_REASON, env=ENV_PATH)) from None
    except ResponseError as error:
        if _NOAUTH_PREFIX not in str(error):
            raise
        raise LocalRedisRefused(_IN_USE_ERROR.format(conf=platform.conf, reason=_AUTH_REASON, env=ENV_PATH)) from None
    except (RedisError, OSError):
        return  # Not running: nothing uses it.
    finally:
        client.close()
    others = clients - 1
    if others > 0:
        reason = _OTHER_CLIENTS_REASON.format(count=others)
        raise LocalRedisRefused(_IN_USE_ERROR.format(conf=platform.conf, reason=reason, env=ENV_PATH))


def _answers(url: str, username: str | None, password: str) -> bool:
    client = Redis.from_url(url, username=username, password=password, socket_timeout=_PROBE_TIMEOUT_S)
    try:
        return bool(client.ping())
    except (RedisError, OSError):
        return False
    finally:
        client.close()


def _await_answer(platform: _Platform, password: str) -> None:
    url = _UNIX_SCHEME + str(platform.socket)
    deadline = time.monotonic() + _SOCKET_WAIT_S
    while time.monotonic() < deadline:
        if _answers(url, _USERNAME, password):
            return
        time.sleep(_SOCKET_POLL_S)
    raise LocalRedisRefused(_UNREACHABLE_ERROR.format(socket=platform.socket, seconds=_SOCKET_WAIT_S, env=ENV_PATH))


def _operator_configured(environment: dict[str, str]) -> bool:
    """Whether the environment names a local Redis of the operator's own, at no socket this module manages, that answers."""
    url = environment.get(_Variable.LOCAL_URL)
    if not url or url in _MANAGED_SOCKETS:
        return False
    username = environment.get(_Variable.LOCAL_USERNAME) or None
    return _answers(url, username, environment.get(_Variable.LOCAL_PASSWORD, ""))


def ensure_local_redis() -> bool:
    """Configure and verify the local Redis; True when something changed. Raises ``LocalRedisRefused``."""
    environment = read_environment_file(ENV_PATH)
    cluster_url = environment.get(_Variable.CLUSTER_URL) or environment.get(_Variable.EARLIER_CLUSTER_URL)
    if cluster_is_on_this_computer(cluster_url):
        logger.info(_SKIPPED_EVENT)
        return False
    if _operator_configured(environment):
        logger.info(_OPERATOR_OWNED_EVENT)
        return False
    platform = _platform()
    password = environment.get(_Variable.LOCAL_PASSWORD) or secrets.token_urlsafe(_PASSWORD_BYTES)
    if platform.brew is not None:
        platform.socket.parent.mkdir(parents=True, exist_ok=True)
        platform.socket.parent.chmod(0o700)
    current = _read_conf(platform)
    if _BLOCK_START not in current:
        _refuse_if_taken(platform, current)
    wanted = _with_block(current, _block(platform, password))
    changed = wanted != current or (platform.privileged and not _drop_in_current(platform))
    if changed:
        if wanted != current:
            _write_conf(platform, wanted)
        _restart(platform)
    elif not _answers(_UNIX_SCHEME + str(platform.socket), _USERNAME, password):
        _restart(platform)
        changed = True
    _await_answer(platform, password)
    write_environment_values(
        ENV_PATH,
        {
            _Variable.LOCAL_URL: _UNIX_SCHEME + str(platform.socket),
            _Variable.LOCAL_USERNAME: _USERNAME,
            _Variable.LOCAL_PASSWORD: password,
        },
    )
    logger.info(_CONFIGURED_EVENT if changed else _UNCHANGED_EVENT, socket=str(platform.socket))
    return changed
