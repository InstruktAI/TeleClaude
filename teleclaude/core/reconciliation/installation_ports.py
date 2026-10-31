"""The infrastructure ports the install act and rollback drive: git, builds, processes and the pointer.

Every method here executes one step and decides nothing; which step runs, in what order, and what a
failure means belong to ``install_act``. The service lifecycle is reached only through a release's own
``bin/daemon-control.sh`` — the active release through ``current``, or a project checkout's own script
while the platform still runs from it — never through ``make`` and never from a caller's directory.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.tui.processes import live_tui_start_commits, signal_tui_reload
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core.integration.daemon_window import (
    Lifecycle,
    StopAttempt,
    StopOutcome,
    script_lifecycle,
    start_until_verified,
    stop_when_quiet,
)
from teleclaude.core.integration.maintenance_output import secret_output_masker
from teleclaude.core.migration_signal import MigrationExitCode
from teleclaude.core.reconciliation.install_act import InstallInProgress, StepVerdict, StopVerdict
from teleclaude.core.reconciliation.installation import InstallationLayout, switch_current
from teleclaude.core.reconciliation.installation_release import (
    fetch_source,
    keep_repository,
    prepare_release,
    release_process_environment,
    remove_release,
    resolve_commit,
)
from teleclaude.core.reconciliation.live_surfaces import publish_telec
from teleclaude.core.reconciliation.release_transition import Refusal, transition_refusal
from teleclaude.git import Repo
from teleclaude.runtime.command_runner import COMMAND_START_FAILURE_EXIT_CODE, run_process_group_command
from teleclaude.runtime.daemon_shutdown_control import ControlRefusal, NothingListening, read_health

logger = get_logger(__name__)

_LOCK_FILENAME = "install.lock"
_LOCK_MODE = "a+"
_TEXT_ENCODING = "utf-8"
_LIFECYCLE_SCRIPT = Path("bin") / "daemon-control.sh"
_RELEASE_PYTHON = Path(".venv") / "bin" / "python"
_MIGRATE_MODULE = "teleclaude.install.migrate_release"
_MODULE_OPTION = "-m"
_TARGET_OPTION = "--target"
_PREVIOUS_OPTION = "--previous"
_REPOSITORY_OPTION = "--repository"
_MIGRATE_TIMEOUT_SECONDS = 3600.0
_LOCAL_REDIS_MODULE = "teleclaude.install.local_redis"
_LOCAL_REDIS_SOURCE = Path("teleclaude") / "install" / "local_redis.py"
_PREPARE_OPTION = "--prepare"
# A Redis package install is the slow part; the daemon keeps serving throughout.
_LOCAL_REDIS_PREPARE_TIMEOUT_SECONDS = 1200.0
_LOCAL_REDIS_PREPARE_FAILED_EVENT = "install_local_redis_preparation_failed"
# The statuses that say no migration started that the record does not hold: the entrypoint's own plain
# failure, and a command that could not start at all. Any other end, a kill or a crash included, is uncertain.
_MIGRATE_CERTAIN_FAILURES = frozenset({MigrationExitCode.FAILED, COMMAND_START_FAILURE_EXIT_CODE})
_PUBLICATION_MODULE = "teleclaude.entrypoints.install_publication"
_SCHEMA_MODULE = "teleclaude.core.reconciliation.config_schemas"
_PLUMBING_MODULE = "teleclaude.project_setup.plumbing"
_RELEASE_OPTION = "--release"
_PUBLISH_TIMEOUT_SECONDS = 900.0
# A release that ships the receiver's socket unit runs a receiver that adopts the socket its unit holds; an earlier
# one cannot use those units (ADR-0148, ADR-0150).
_INGRESS_RECEIVER_SOCKET_UNIT = Path("templates") / "teleclaude-ingress-receiver.socket"
_WITHDRAW_TIMEOUT_SECONDS = 120.0
_PUBLISH_FAILED = "{module} exited {exit_code}: {output}"
_PUBLISH_TIMED_OUT = "{module} did not finish within {seconds:.0f}s"
_STOP_CLEANUP_WARNING_EVENT = "install_stop_cleanup_failure"
_NO_LIFECYCLE = "no lifecycle is available to stop the serving daemon through"
_STOP_NO_OUTCOME = "the lifecycle recorded no stop outcome"
_STOP_COMMAND_FAILED = "the stop command could not run: {error_kind}"
_STOP_WITHHELD = "the lifecycle withheld the stop ({outcome})"
_MIGRATE_FAILED = "exit {exit_code}: {output}"
_MIGRATE_TIMED_OUT = "the migration entrypoint did not finish within {seconds:.0f}s"
_NO_OUTPUT = "no output"
_TUI_RELOAD_EVENT = "install_tuis_reloaded"


class LiveInstallPorts:
    """The install act's ports bound to one installation on this machine."""

    def __init__(self, layout: InstallationLayout | None = None) -> None:
        self._layout = layout or InstallationLayout()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold the installation against a second act; a second caller is refused at once."""
        self._layout.root.mkdir(parents=True, exist_ok=True)
        with (self._layout.root / _LOCK_FILENAME).open(_LOCK_MODE, encoding=_TEXT_ENCODING) as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise InstallInProgress from error
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def fetch(self, source: str | None) -> None:
        """Keep the repository of the source and bring it up to date."""
        keep_repository(self._layout, source)
        fetch_source(self._layout)

    def resolve(self, reference: str) -> str:
        """The full commit a reference names in the kept repository."""
        return resolve_commit(self._layout, reference)

    def refusal(self, active: str, target: str, release_tag: str | None) -> Refusal | None:
        """Why ``target`` is not an admitted forward step over ``active``."""
        return transition_refusal(Repo(str(self._layout.repository)), active, target, release_tag)

    def prepare(self, revision: str) -> None:
        """Add and build the release, then let it prepare this machine for itself, while the daemon serves."""
        prepare_release(self._layout, revision)
        self._prepare_machine(revision)

    def _prepare_machine(self, revision: str) -> None:
        """Run the release's local Redis preparation; it logs its own refusals and never fails the install."""
        release = self._layout.release_path(revision)
        if not (release / _LOCAL_REDIS_SOURCE).is_file():
            return
        result = run_process_group_command(
            [str(release / _RELEASE_PYTHON), _MODULE_OPTION, _LOCAL_REDIS_MODULE, _PREPARE_OPTION],
            release,
            release_process_environment(),
            timeout_seconds=_LOCAL_REDIS_PREPARE_TIMEOUT_SECONDS,
            capture_output=secret_output_masker(release),
        )
        if result.timed_out or result.exit_code != 0:
            logger.warning(
                _LOCAL_REDIS_PREPARE_FAILED_EVENT,
                revision=revision,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                output_tail=result.output_tail,
            )

    def daemon_serving(self) -> bool:
        """Whether a daemon serves the machine: anything listening on its socket counts."""
        try:
            read_health(API_SOCKET_PATH)
        except NothingListening:
            return False
        except ControlRefusal:
            return True
        return True

    def stop(self, checkout: Path | None) -> StopVerdict:
        """Stop the serving daemon through the active release's lifecycle, or the checkout's when none is active."""
        lifecycle = self._stop_lifecycle(checkout)
        if lifecycle is None:
            return StopVerdict(stopped=False, reason=_NO_LIFECYCLE)
        return self._verdict(stop_when_quiet(lifecycle, self._layout.root, {}))

    def _verdict(self, attempt: StopAttempt) -> StopVerdict:
        """Whether the lifecycle recorded the daemon stopped, and the reason when it did not."""
        if attempt.error_kind is not None:
            return StopVerdict(stopped=False, reason=_STOP_COMMAND_FAILED.format(error_kind=attempt.error_kind))
        if attempt.outcome is None:
            output = attempt.result.output_tail if attempt.result is not None else None
            return StopVerdict(stopped=False, reason=output or _STOP_NO_OUTCOME)
        if attempt.outcome is StopOutcome.STOPPED_CLEANUP_FAILURE:
            logger.warning(
                _STOP_CLEANUP_WARNING_EVENT, output_tail=attempt.result.output_tail if attempt.result else None
            )
        if attempt.outcome in (StopOutcome.STOPPED, StopOutcome.STOPPED_CLEANUP_FAILURE):
            return StopVerdict(stopped=True)
        output = attempt.result.output_tail if attempt.result is not None else None
        return StopVerdict(stopped=False, reason=output or _STOP_WITHHELD.format(outcome=attempt.outcome.value))

    def migrate(self, previous: str | None, target: str) -> StepVerdict:
        """Run the target release's migration entrypoint with that release's own interpreter."""
        release = self._layout.release_path(target)
        command = [
            str(release / _RELEASE_PYTHON),
            _MODULE_OPTION,
            _MIGRATE_MODULE,
            _TARGET_OPTION,
            target,
            _REPOSITORY_OPTION,
            str(self._layout.repository),
        ]
        if previous is not None:
            command += [_PREVIOUS_OPTION, previous]
        result = run_process_group_command(
            command,
            release,
            release_process_environment(),
            timeout_seconds=_MIGRATE_TIMEOUT_SECONDS,
            capture_output=secret_output_masker(release),
        )
        if result.timed_out:
            return StepVerdict(
                succeeded=False, reason=_MIGRATE_TIMED_OUT.format(seconds=_MIGRATE_TIMEOUT_SECONDS), unaccounted=True
            )
        if result.exit_code != 0:
            return StepVerdict(
                succeeded=False,
                reason=_MIGRATE_FAILED.format(exit_code=result.exit_code, output=result.output_tail or _NO_OUTPUT),
                unaccounted=result.exit_code not in _MIGRATE_CERTAIN_FAILURES,
            )
        return StepVerdict(succeeded=True)

    def switch(self, revision: str | None) -> None:
        """Point ``current`` at the release of ``revision`` in one atomic step.

        Switching to a release that cannot run the ingress receiver's units first withdraws them, through the
        outgoing release's installer, so that release's daemon serves the inbound endpoints on its port again. A
        withdrawal that fails leaves ``current`` where it was and raises.
        """
        if revision is not None and not (self._layout.release_path(revision) / _INGRESS_RECEIVER_SOCKET_UNIT).is_file():
            self._withdraw_ingress_receiver(revision)
        switch_current(self._layout, revision)

    def _withdraw_ingress_receiver(self, revision: str) -> None:
        outgoing = self._layout.active_release()
        if outgoing is None:
            return
        result = run_process_group_command(
            [
                "bash",
                "-c",
                "source bin/init/install_services.sh && { ! declare -F withdraw_ingress_receiver >/dev/null"
                " || withdraw_ingress_receiver; }",
            ],
            outgoing,
            {**release_process_environment(), "PROJECT_ROOT": str(outgoing)},
            timeout_seconds=_WITHDRAW_TIMEOUT_SECONDS,
            capture_output=secret_output_masker(outgoing),
        )
        if result.timed_out or result.exit_code != 0:
            logger.error(
                "ingress_receiver_withdrawal_failed",
                revision=revision,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                output_tail=result.output_tail,
            )
            raise RuntimeError(f"could not withdraw the ingress receiver before switching to {revision}")

    def start_and_verify(self, revision: str | None, checkout: Path | None) -> StepVerdict:
        """Start through ``current`` (or the checkout's lifecycle) and verify the daemon serves ``revision``."""
        if revision is None and checkout is not None:
            lifecycle = script_lifecycle(checkout / _LIFECYCLE_SCRIPT)
            attempt = start_until_verified(lifecycle, lambda _health: True)
        else:
            lifecycle = script_lifecycle(self._layout.current / _LIFECYCLE_SCRIPT)
            attempt = start_until_verified(
                lifecycle, lambda health: revision is None or health.start_commit == revision
            )
        return StepVerdict(succeeded=attempt.verified, reason=attempt.reason)

    def ensure_stopped(self) -> StopVerdict:
        """Stop the daemon through ``current``'s lifecycle, answering whether the lifecycle recorded it stopped."""
        lifecycle = script_lifecycle(self._layout.current / _LIFECYCLE_SCRIPT)
        return self._verdict(stop_when_quiet(lifecycle, self._layout.root, {}))

    def publish_cli(self) -> None:
        """Publish the global ``telec`` through ``current``."""
        publish_telec(self._layout)

    def reload_tuis(self) -> None:
        """Signal every running terminal interface through presentation's registry."""
        reached = signal_tui_reload()
        logger.info(_TUI_RELOAD_EVENT, pids=reached)

    def held_tui_revisions(self) -> frozenset[str | None]:
        """The start commit each running terminal interface's record names, ``None`` where it names none."""
        return frozenset(commit for _pid, commit in live_tui_start_commits())

    def prune(self, keep: frozenset[str]) -> None:
        """Remove every release folder except the ones named; the act's keep-set names what running terminal interfaces hold."""
        for revision in self._layout.installed_revisions():
            if revision not in keep:
                remove_release(self._layout, revision)

    def publish(self, revision: str) -> str | None:
        """Publish the release's configuration schemas, and its documentation and agent artifacts where no platform checkout publishes them, then converge every registered root and the platform home to its templates, through its own interpreter."""
        release = self._layout.release_path(revision)
        python = str(release / _RELEASE_PYTHON)
        for arguments in (
            (_MODULE_OPTION, _PUBLICATION_MODULE, _RELEASE_OPTION, str(release)),
            (_MODULE_OPTION, _SCHEMA_MODULE),
            (_MODULE_OPTION, _PLUMBING_MODULE),
        ):
            result = run_process_group_command(
                [python, *arguments],
                release,
                release_process_environment(),
                timeout_seconds=_PUBLISH_TIMEOUT_SECONDS,
                capture_output=secret_output_masker(release),
            )
            if result.timed_out:
                return _PUBLISH_TIMED_OUT.format(module=arguments[1], seconds=_PUBLISH_TIMEOUT_SECONDS)
            if result.exit_code != 0:
                return _PUBLISH_FAILED.format(
                    module=arguments[1], exit_code=result.exit_code, output=result.output_tail or _NO_OUTPUT
                )
        return None

    def _stop_lifecycle(self, checkout: Path | None) -> Lifecycle | None:
        script = self._layout.current / _LIFECYCLE_SCRIPT
        if script.is_file():
            return script_lifecycle(script)
        if checkout is not None:
            return script_lifecycle(checkout / _LIFECYCLE_SCRIPT)
        return None
