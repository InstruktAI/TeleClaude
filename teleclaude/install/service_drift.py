"""Owed-probe for service deployment: which host services installation would deploy or withdraw.

An on-demand run never deploys a service definition or reloads a running service. This
probe asks the question installation answers without acting on it: it prints one line per
service whose deployed definition differs from the rendered one, and per service
installation would withdraw, and prints nothing when none is due. It exits non-zero when it
cannot render or compare, so the run says it could not tell.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.project_setup.macos_setup import tmux_server_definition_drift

logger = get_logger(__name__)

_INSTALL_SERVICES_SCRIPT = Path("bin") / "init" / "install_services.sh"
_CHECK_FLAG = "--check"
_BASH_EXECUTABLE = "bash"
_PROBE_FINISHED_EVENT = "service_drift_probe_finished"
_CHECK_FAILED = "Could not compare the service definitions installation would deploy: {detail}"
_TMUX_CHECK_FAILED = "Could not compare the tmux server service definition: {error}"
_DUE_EXIT_CODE = 0
_UNDECIDABLE_EXIT_CODE = 1


def check_service_definitions(root: Path) -> tuple[tuple[str, ...], str | None]:
    """Run the installer's check mode; return the drift lines it printed and, when it failed, why."""
    # The service definitions are rendered and compared by the installer's own shell functions,
    # which have no Python API; the check mode writes nothing.
    result = subprocess.run(
        [_BASH_EXECUTABLE, str(root / _INSTALL_SERVICES_SCRIPT), _CHECK_FLAG],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    lines = tuple(line for line in result.stdout.splitlines() if line.strip())
    if result.returncode != 0:
        return lines, (result.stderr.strip() or result.stdout.strip() or str(result.returncode))
    return lines, None


def run_probe(root: Path) -> int:
    """Print every due service line and return the probe's exit status."""
    lines, failure = check_service_definitions(root)
    findings = list(lines)
    undecidable: list[str] = []
    if failure is not None:
        undecidable.append(_CHECK_FAILED.format(detail=failure))
    try:
        tmux_drift = tmux_server_definition_drift()
    except (FileNotFoundError, OSError) as exc:
        tmux_drift = None
        undecidable.append(_TMUX_CHECK_FAILED.format(error=exc))
    if tmux_drift is not None:
        findings.append(tmux_drift)
    for line in findings:
        print(line)
    for line in undecidable:
        print(line, file=sys.stderr)
    logger.info(_PROBE_FINISHED_EVENT, due_count=len(findings), undecidable_count=len(undecidable))
    return _UNDECIDABLE_EXIT_CODE if undecidable else _DUE_EXIT_CODE


def main() -> int:
    """Run the probe for the command line's working root."""
    return run_probe(Path.cwd().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
