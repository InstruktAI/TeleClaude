"""Frontend package-manager detection and command forms.

Detects which JavaScript package manager governs a frontend project — from the
``package.json`` ``packageManager`` field (corepack's authoritative pin) or,
failing that, the lockfile present — and exposes the exec and run-script command
forms each manager uses. The lint and test pipelines consume this so no surface
hardcodes a single package manager. The bootstrap installer mirrors this
detection in ``bin/install.sh`` (it runs before the Python environment exists).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class PackageManager(StrEnum):
    """A supported JavaScript package manager."""

    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"


# Lockfile basename → manager, in detection priority order (most specific first).
# When more than one lockfile is present — a mixed-tooling mistake — the
# highest-priority match wins and the ambiguity is logged rather than silent.
_LOCKFILE_MANAGERS: tuple[tuple[str, PackageManager], ...] = (
    ("bun.lock", PackageManager.BUN),
    ("bun.lockb", PackageManager.BUN),
    ("pnpm-lock.yaml", PackageManager.PNPM),
    ("yarn.lock", PackageManager.YARN),
    ("package-lock.json", PackageManager.NPM),
)


@dataclass(frozen=True)
class PackageManagerCommands:
    """Command forms for one package manager.

    ``exec`` runs an installed binary (eslint, tsc); ``run_script`` runs a
    ``package.json`` script (test). They are distinct because ``bun`` overloads
    ``bun test`` for its native runner — a project's ``test`` script is only
    reachable through ``bun run test``.
    """

    manager: PackageManager

    def exec(self, binary: str, args: list[str]) -> list[str]:
        """Command that runs an installed binary from the project."""
        if self.manager is PackageManager.NPM:
            return ["npx", "--yes", binary, *args]
        if self.manager is PackageManager.PNPM:
            return ["pnpm", "exec", binary, *args]
        if self.manager is PackageManager.YARN:
            return ["yarn", "exec", binary, *args]
        return ["bunx", binary, *args]

    def run_script(self, script: str, args: list[str]) -> list[str]:
        """Command that runs a ``package.json`` script, forwarding extra args."""
        cmd = [self.manager.value, "run", script]
        if args:
            cmd += ["--", *args]
        return cmd


def detect(frontend_root: Path) -> PackageManager:
    """Detect the package manager governing ``frontend_root``.

    Resolution order: the ``packageManager`` field (corepack's authoritative
    pin) first, then lockfile presence. Defaults to npm when no signal exists —
    npm is always available wherever Node is.
    """
    pinned = _manager_from_package_json(frontend_root)
    if pinned is not None:
        return pinned
    return _manager_from_lockfiles(frontend_root)


def commands_for(frontend_root: Path) -> PackageManagerCommands:
    """Return the command forms for the manager detected at ``frontend_root``."""
    return PackageManagerCommands(detect(frontend_root))


def _manager_from_package_json(frontend_root: Path) -> PackageManager | None:
    """Read the corepack ``packageManager`` pin, e.g. ``pnpm@9.12.0+sha512…``."""
    package_json = frontend_root / "package.json"
    if not package_json.exists():
        return None
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    pin = data.get("packageManager")
    if not isinstance(pin, str):
        return None
    name = pin.split("@", 1)[0].strip()
    try:
        return PackageManager(name)
    except ValueError:
        return None


def _manager_from_lockfiles(frontend_root: Path) -> PackageManager:
    """Resolve the manager from lockfiles, defaulting to npm when none exist."""
    present = [manager for basename, manager in _LOCKFILE_MANAGERS if (frontend_root / basename).exists()]
    distinct = set(present)
    if len(distinct) > 1:
        logger.warning(
            "Multiple package-manager lockfiles in %s (%s) — using %s by priority",
            frontend_root,
            ", ".join(sorted(m.value for m in distinct)),
            present[0].value,
        )
    if present:
        return present[0]
    return PackageManager.NPM
