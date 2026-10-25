"""Create the machine's installation and move the platform onto it: the bootstrap and the move off a checkout.

Both reach the live platform through the install act, never through a second installer. The bootstrap
runs on a machine with no platform: it keeps the source's repository, installs the revision it is given
(the source's latest release when none is named) through the act's initial provisioning path, and publishes
``telec`` from it. The move runs on a machine whose live platform is its project checkout: it makes the
machine environment file a real file in the platform home, installs a release at a revision the forward-only
rule admits over the commit the checkout runs — a controlled restart, stopped through the checkout's own
lifecycle — and leaves the checkout an ordinary registered project. Rebinding the home-level surfaces to
``current`` is the installer's convergence run from the installed release (``bin/install.sh``)
(``local/projects/teleclaude/spec/feature/reconciliation/installed-releases``).
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import tempfile
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config._models import ReleaseChannel
from teleclaude.config.compatibility_series import CompatibilitySeries
from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.machine import config
from teleclaude.core.reconciliation.channel_target import (
    ChannelTarget,
    ChannelTargetError,
    channel_target,
    release_tag_of,
)
from teleclaude.core.reconciliation.install_act import InstallRequest, InstallResult, InstallStatus, install
from teleclaude.core.reconciliation.installation import InstallationLayout
from teleclaude.core.reconciliation.installation_ports import LiveInstallPorts
from teleclaude.core.reconciliation.installation_release import ReleasePreparationError
from teleclaude.git import GitCommandError, Repo
from teleclaude.logging_config import setup_logging
from teleclaude.paths import ENV_PATH

logger = get_logger(__name__)

_BOOTSTRAP_VERB = "bootstrap"
_MOVE_VERB = "move"
_SOURCE_OPTION = "--source"
_CHECKOUT_OPTION = "--checkout"
_REVISION_OPTION = "--revision"
_REMOTE_NAME = "origin"
_ENV_MODE_MASK = 0o777
_TEXT_ENCODING = "utf-8"
_ENV_STAGING_SUFFIX = ".moving"
_MOVED_ENV_EVENT = "installation_move_environment_file"
_NO_SOURCE = "the checkout {checkout} has no origin remote to install from"
_NO_RUNNING_REVISION = "the commit {checkout} runs could not be read: {error}"
_NO_TARGET = "the source offers no revision to install: {error}"
_RESULT_LINE = "{status}: {revision}"
_REASON_LINE = "  {reason}"
_PUBLICATION_LINE = "  publication owed: {failure}"
_FAILED_EXIT_CODE = 1


class MoveRefused(RuntimeError):
    """The move or bootstrap cannot start; nothing changed, and the message says why."""


def first_install_target(layout: InstallationLayout) -> ChannelTarget:
    """The latest release the kept repository holds; a source that tags none has no first install to offer.

    The first install is the source's latest release and nothing else: no other class of source is
    substituted, so a source with no release is reported rather than activated from its mainline.
    """
    return channel_target(layout, ReleaseChannel.BETA, None)


def bootstrap(source: str, layout: InstallationLayout | None = None, revision: str | None = None) -> InstallResult:
    """Keep the source's repository and install ``revision`` as the machine's first active release.

    Without a named revision the first release is the source's latest one. A named revision is built into the
    request the way ``telec app install <revision>`` builds it.
    """
    resolved = layout or InstallationLayout()
    ports = LiveInstallPorts(resolved)
    ports.fetch(source)
    if revision is not None:
        return install(
            InstallRequest(target=revision, release_tag=release_tag_of(revision), source=source), ports, resolved
        )
    target = first_install_target(resolved)
    return install(
        InstallRequest(target=target.reference, release_tag=target.release_tag, source=source), ports, resolved
    )


def make_environment_file_real(env_path: Path, checkout: Path) -> bool:
    """Make the machine environment file a real file in the platform home; whether it had to move.

    The home's file is a link into the checkout (or absent while the checkout holds one): its content is
    carried into a real file, owner-only as it was, and put in place atomically, so a release switch can
    never lose it and a checkout can never hold it.
    """
    source: Path | None = None
    if env_path.is_symlink():
        source = env_path.resolve()
    elif not env_path.exists() and (checkout / env_path.name).is_file():
        source = checkout / env_path.name
    if source is None or not source.is_file():
        return False
    mode = stat.S_IMODE(source.stat().st_mode) & _ENV_MODE_MASK
    env_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding=_TEXT_ENCODING, dir=env_path.parent, suffix=_ENV_STAGING_SUFFIX, delete=False
    ) as staged:
        staged_path = Path(staged.name)
        staged.write(source.read_text(encoding=_TEXT_ENCODING))
    staged_path.chmod(mode)
    os.replace(staged_path, env_path)
    logger.info(_MOVED_ENV_EVENT, path=str(env_path), carried_from=str(source))
    return True


def _origin_of(checkout: Path) -> str:
    try:
        return str(Repo(str(checkout)).remote(_REMOTE_NAME).url)
    except (GitCommandError, ValueError) as error:
        raise MoveRefused(_NO_SOURCE.format(checkout=checkout)) from error


def _running_revision(checkout: Path) -> str:
    try:
        return Repo(str(checkout)).head.commit.hexsha
    except (GitCommandError, ValueError, OSError) as error:
        raise MoveRefused(_NO_RUNNING_REVISION.format(checkout=checkout, error=error)) from error


def move_off_checkout(
    checkout: Path,
    channel: ReleaseChannel | None = None,
    series: CompatibilitySeries | None = None,
    layout: InstallationLayout | None = None,
) -> InstallResult:
    """Move the platform that runs from ``checkout`` onto an installation, in one controlled restart."""
    resolved = layout or InstallationLayout()
    source = _origin_of(checkout)
    running = _running_revision(checkout)
    make_environment_file_real(ENV_PATH, checkout)
    ports = LiveInstallPorts(resolved)
    ports.fetch(source)
    try:
        target = channel_target(resolved, channel, series) if channel is not None else first_install_target(resolved)
    except ChannelTargetError as error:
        raise MoveRefused(_NO_TARGET.format(error=error)) from error
    request = InstallRequest(
        target=target.reference,
        release_tag=target.release_tag,
        source=source,
        checkout=checkout,
        running=running,
    )
    return install(request, ports, resolved)


def _machine_channel() -> tuple[ReleaseChannel | None, CompatibilitySeries | None]:
    """The channel and series the machine's own configuration declares; neither when it does not load."""
    try:
        return config.deployment.channel, config.deployment.series
    except (ConfigLoadError, FileNotFoundError, ValueError):
        return None, None


def _report(result: InstallResult) -> int:
    print(_RESULT_LINE.format(status=result.status.value, revision=result.revision or ""))
    if result.reason:
        print(_REASON_LINE.format(reason=result.reason), file=sys.stderr)
    if result.publication_failure:
        print(_PUBLICATION_LINE.format(failure=result.publication_failure), file=sys.stderr)
    failed = result.status in (InstallStatus.REFUSED, InstallStatus.FAILED) or result.publication_failure is not None
    return _FAILED_EXIT_CODE if failed else 0


def main(arguments: list[str] | None = None) -> int:
    """Run ``bootstrap --source <url> [--revision <reference>]`` or ``move --checkout <path>``; non-zero when the machine is not on an installation."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    verbs = parser.add_subparsers(dest="verb", required=True)
    bootstrap_parser = verbs.add_parser(_BOOTSTRAP_VERB)
    bootstrap_parser.add_argument(_SOURCE_OPTION, required=True)
    bootstrap_parser.add_argument(_REVISION_OPTION)
    move_parser = verbs.add_parser(_MOVE_VERB)
    move_parser.add_argument(_CHECKOUT_OPTION, type=Path, required=True)
    options = parser.parse_args(arguments)
    try:
        if options.verb == _BOOTSTRAP_VERB:
            return _report(bootstrap(options.source, revision=options.revision))
        channel, series = _machine_channel()
        return _report(move_off_checkout(options.checkout.resolve(), channel, series))
    except (MoveRefused, ReleasePreparationError, ChannelTargetError, OSError) as error:
        print(str(error), file=sys.stderr)
        return _FAILED_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
