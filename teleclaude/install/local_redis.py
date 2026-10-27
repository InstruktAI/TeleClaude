"""Set up this computer's local Redis for its local events (``local/projects/teleclaude/design/architecture/event-delivery``).

A computer whose cluster Redis is remote runs the operating system's Redis as its local Redis: on a Unix socket only
its user and the Redis service can open, with the TCP port off, the default user off and one ACL user whose password
lives in the machine environment. On Linux the Redis service runs with the TeleClaude user's primary group, so every
process of that user can open the socket at once, sessions already running included.

Nothing is set up where the cluster Redis is on this computer, since it already keeps local events local, or where
the environment names a local Redis of the operator's own that answers. A Redis that another program uses is never
taken over: the stage refuses and names the variables that point TeleClaude at a dedicated instance instead.
Running it again changes nothing that is already in place.
"""

from __future__ import annotations

import grp
import os
import secrets
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
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ENV_PATH, TELECLAUDE_HOME

logger = get_logger("teleclaude.install.local_redis")


class _Variable(StrEnum):
    CLUSTER_URL = "REDIS_CLUSTER_URL"
    EARLIER_CLUSTER_URL = "REDIS_URL"
    LOCAL_URL = "REDIS_LOCAL_URL"
    LOCAL_USERNAME = "REDIS_LOCAL_USERNAME"
    LOCAL_PASSWORD = "REDIS_LOCAL_PASSWORD"


_USERNAME: Final = "teleclaude"
_UNIX_SCHEME: Final = "unix://"
_LOOPBACK_HOSTS: Final = frozenset({"localhost", "::1"})
_LOOPBACK_IPV4_PREFIX: Final = "127."
_BLOCK_START: Final = "# >>> teleclaude local redis"
_BLOCK_END: Final = "# <<< teleclaude local redis"
_SOCKET_WAIT_S: Final = 15.0
_SOCKET_POLL_S: Final = 0.25
_PASSWORD_BYTES: Final = 32
_MACOS_SOCKET_DIR: Final = TELECLAUDE_HOME / "redis"
_MACOS_SOCKET_MODE: Final = "700"
_LINUX_CONF: Final = Path("/etc/redis/redis.conf")
_LINUX_SOCKET: Final = Path("/run/redis/redis-server.sock")
_LINUX_SOCKET_MODE: Final = "770"
_LINUX_SERVICE: Final = "redis-server"
_LINUX_DROP_IN: Final = Path("/etc/systemd/system/redis-server.service.d/teleclaude.conf")
_DROP_IN_TEMPLATE: Final = (
    "# TeleClaude: the local Redis socket belongs to the TeleClaude user's group.\n[Service]\nGroup={group}\n"
)
_PORT_DIRECTIVE: Final = "port"
_DEFAULT_PORT: Final = 6379
_LOOPBACK_ADDRESS: Final = "127.0.0.1"
_CLIENTS_SECTION: Final = "clients"
_CONNECTED_CLIENTS: Final = "connected_clients"
_NOAUTH_PREFIX: Final = "NOAUTH"
_BLOCK_TEMPLATE: Final = (
    "{start}\n"
    "port 0\n"
    "unixsocket {socket}\n"
    "unixsocketperm {mode}\n"
    "user default off\n"
    "user {username} on >{password} ~* &* +@all\n"
    "{end}\n"
)
_SKIPPED_EVENT: Final = "local_redis_skipped_cluster_on_this_computer"
_OPERATOR_OWNED_EVENT: Final = "local_redis_operator_configured"
_CONFIGURED_EVENT: Final = "local_redis_configured"
_UNCHANGED_EVENT: Final = "local_redis_unchanged"
_FAILED_EVENT: Final = "local_redis_setup_failed"
_UNREACHABLE_ERROR: Final = "the local Redis did not answer on {socket} with its ACL user within {seconds:g}s"
_UNSUPPORTED_ERROR: Final = "no local Redis setup for platform {platform}"
_IN_USE_ERROR: Final = (
    "the Redis configured in {conf} is in use by another program ({reason}); TeleClaude does not take it over. "
    "Run a dedicated Redis on a Unix socket with an ACL user, set REDIS_LOCAL_URL, REDIS_LOCAL_USERNAME and "
    "REDIS_LOCAL_PASSWORD in {env} to reach it, and re-run make install"
)
_OTHER_CLIENTS_REASON: Final = "{count} other connected clients"
_AUTH_REASON: Final = "it requires authentication TeleClaude was not given"


@dataclass(frozen=True)
class _Platform:
    """Where this operating system's Redis keeps its configuration and socket, and how it is restarted."""

    conf: Path
    socket: Path
    socket_mode: str
    privileged: bool


def _sudo(*command: str, stdin: str | None = None) -> str:
    # The system Redis configuration and service belong to root. An interactive install may prompt for the
    # password; an unattended one fails at once instead of waiting for a prompt nobody answers.
    prefix = ["sudo"] if sys.stdin.isatty() else ["sudo", "-n"]
    return subprocess.run([*prefix, *command], input=stdin, check=True, capture_output=True, text=True).stdout


def cluster_is_on_this_computer(cluster_url: str | None) -> bool:
    """Whether the cluster Redis URL names this computer, so it already serves local events locally."""
    if not cluster_url:
        return True
    host = urlparse(cluster_url).hostname or ""
    return host in _LOOPBACK_HOSTS or host.startswith(_LOOPBACK_IPV4_PREFIX)


def _platform() -> _Platform:
    if sys.platform == "darwin":
        # `brew --prefix` names Homebrew's root; no Python API exposes it.
        prefix = subprocess.run(["brew", "--prefix"], check=True, capture_output=True, text=True).stdout.strip()
        return _Platform(
            Path(prefix) / "etc" / "redis.conf", _MACOS_SOCKET_DIR / "redis.sock", _MACOS_SOCKET_MODE, False
        )
    if sys.platform.startswith("linux"):
        return _Platform(_LINUX_CONF, _LINUX_SOCKET, _LINUX_SOCKET_MODE, True)
    raise RuntimeError(_UNSUPPORTED_ERROR.format(platform=sys.platform))


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


def _write_conf(platform: _Platform, text: str) -> None:
    if platform.privileged:
        _sudo("tee", str(platform.conf), stdin=text)
    else:
        platform.conf.write_text(text)


def _read_conf(platform: _Platform) -> str:
    try:
        return platform.conf.read_text()
    except PermissionError:
        if not platform.privileged:
            raise
        return _sudo("cat", str(platform.conf))


def _drop_in() -> str:
    return _DROP_IN_TEMPLATE.format(group=grp.getgrgid(os.getgid()).gr_name)


def _drop_in_current() -> bool:
    try:
        return _LINUX_DROP_IN.read_text() == _drop_in()
    except OSError:
        return False


def _restart(platform: _Platform) -> None:
    if not platform.privileged:
        # Homebrew's service manager owns the macOS Redis service; it has no Python API.
        subprocess.run(["brew", "services", "restart", "redis"], check=True, capture_output=True)
        return
    if not _drop_in_current():
        _sudo("mkdir", "-p", str(_LINUX_DROP_IN.parent))
        _sudo("tee", str(_LINUX_DROP_IN), stdin=_drop_in())
        _sudo("systemctl", "daemon-reload")
    _sudo("systemctl", "enable", _LINUX_SERVICE)
    _sudo("systemctl", "restart", _LINUX_SERVICE)


def _configured_port(conf_text: str) -> int:
    """The TCP port the configuration ends up with; Redis takes the last directive."""
    port = _DEFAULT_PORT
    for line in conf_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == _PORT_DIRECTIVE and parts[1].isdigit():
            port = int(parts[1])
    return port


def _refuse_if_in_use(platform: _Platform, conf_text: str) -> None:
    """Refuse a Redis this stage never configured while another program is connected to it or has secured it."""
    port = _configured_port(conf_text)
    if port == 0:
        return
    client = Redis(host=_LOOPBACK_ADDRESS, port=port, socket_timeout=2)
    try:
        # The synchronous client returns the parsed section; its stubs also admit the asynchronous result.
        clients = int(cast("dict[str, int]", client.info(_CLIENTS_SECTION))[_CONNECTED_CLIENTS])
    except AuthenticationError:
        raise RuntimeError(_IN_USE_ERROR.format(conf=platform.conf, reason=_AUTH_REASON, env=ENV_PATH)) from None
    except ResponseError as exc:
        if _NOAUTH_PREFIX not in str(exc):
            raise
        raise RuntimeError(_IN_USE_ERROR.format(conf=platform.conf, reason=_AUTH_REASON, env=ENV_PATH)) from None
    except (RedisError, OSError):
        return  # Not running: nothing uses it.
    finally:
        client.close()
    others = clients - 1
    if others > 0:
        reason = _OTHER_CLIENTS_REASON.format(count=others)
        raise RuntimeError(_IN_USE_ERROR.format(conf=platform.conf, reason=reason, env=ENV_PATH))


def _answers(socket: Path, password: str) -> bool:
    client = Redis(unix_socket_path=str(socket), username=_USERNAME, password=password, socket_timeout=2)
    try:
        return bool(client.ping())
    except (RedisError, OSError):
        return False
    finally:
        client.close()


def _await_answer(socket: Path, password: str) -> None:
    deadline = time.monotonic() + _SOCKET_WAIT_S
    while time.monotonic() < deadline:
        if _answers(socket, password):
            return
        time.sleep(_SOCKET_POLL_S)
    raise RuntimeError(_UNREACHABLE_ERROR.format(socket=socket, seconds=_SOCKET_WAIT_S))


def _operator_configured(environment: dict[str, str], platform: _Platform) -> bool:
    """Whether the environment names a local Redis of the operator's own, not this stage's socket, that answers."""
    url = environment.get(_Variable.LOCAL_URL)
    if not url or url == _UNIX_SCHEME + str(platform.socket):
        return False
    password = environment.get(_Variable.LOCAL_PASSWORD, "")
    username = environment.get(_Variable.LOCAL_USERNAME) or None
    client = Redis.from_url(url, username=username, password=password, socket_timeout=2)
    try:
        return bool(client.ping())
    except (RedisError, OSError):
        return False
    finally:
        client.close()


def ensure_local_redis() -> bool:
    """Configure and verify the local Redis; True when something changed."""
    environment = read_environment_file(ENV_PATH)
    cluster_url = environment.get(_Variable.CLUSTER_URL) or environment.get(_Variable.EARLIER_CLUSTER_URL)
    if cluster_is_on_this_computer(cluster_url):
        logger.info(_SKIPPED_EVENT)
        return False
    platform = _platform()
    if _operator_configured(environment, platform):
        logger.info(_OPERATOR_OWNED_EVENT)
        return False
    password = environment.get(_Variable.LOCAL_PASSWORD) or secrets.token_urlsafe(_PASSWORD_BYTES)
    if not platform.privileged:
        _MACOS_SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        _MACOS_SOCKET_DIR.chmod(0o700)
    current = _read_conf(platform)
    if _BLOCK_START not in current:
        _refuse_if_in_use(platform, current)
    wanted = _with_block(current, _block(platform, password))
    changed = wanted != current or (platform.privileged and not _drop_in_current())
    if changed:
        if wanted != current:
            _write_conf(platform, wanted)
        _restart(platform)
    elif not _answers(platform.socket, password):
        _restart(platform)
        changed = True
    _await_answer(platform.socket, password)
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


def main() -> int:
    """Run the local Redis setup as an installer stage."""
    setup_logging()
    try:
        ensure_local_redis()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        logger.error(_FAILED_EVENT, error=str(exc))
        print(f"Local Redis setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
