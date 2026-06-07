"""Internal multi-project file watcher for TeleClaude artifact sync."""

from __future__ import annotations

import fnmatch
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from instrukt_ai_logging import InstruktAILogger, get_logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch

from teleclaude.logging_config import setup_logging
from teleclaude.paths import PROJECTS_MANIFEST_PATH, REPO_ROOT
from teleclaude.project_manifest import load_roots

try:
    import pathspec
except ImportError:
    pathspec = None

if TYPE_CHECKING:
    from pathspec import PathSpec


class _ObserverProtocol(Protocol):
    def schedule(self, handler: FileSystemEventHandler, path: str, recursive: bool) -> ObservedWatch: ...
    def unschedule(self, watch: ObservedWatch) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def join(self) -> None: ...


logger: InstruktAILogger = get_logger("teleclaude.cli.watch")


class SmartWatcher(FileSystemEventHandler):
    """Watch one project root for artifact-relevant changes."""

    _SYNC_EVENT_TYPES = {"created", "modified", "moved", "deleted"}
    _SYNC_TOP_LEVELS = {"docs", "agents", ".agents"}
    _SYNC_FILENAMES = {"AGENTS.master.md", "AGENTS.global.md"}
    _GENERATED_SYNC_OUTPUT_GLOBS = ("docs/**/index.yaml",)
    _GIT_COOLDOWN_S = 10.0

    def __init__(self, project_root: Path, debounce_seconds: float = 2.0):
        self.project_root = project_root.resolve()
        self.debounce_seconds = debounce_seconds
        self.last_run_time = 0.0
        self._last_git_lock_seen = 0.0
        self.spec = self._load_gitignore()
        self._sync()

    def _load_gitignore(self) -> PathSpec | None:  # pyright: ignore[reportInvalidTypeArguments]
        if not pathspec:
            logger.warning("pathspec not installed; .gitignore support disabled")
            return None

        gitignore_path = self.project_root / ".gitignore"
        patterns = [".git/"]

        if gitignore_path.exists():
            with gitignore_path.open("r", encoding="utf-8") as handle:
                patterns.extend(handle.readlines())

        patterns.extend(
            [
                "dist/",
                "__pycache__/",
                ".venv/",
                ".mypy_cache/",
                ".pytest_cache/",
                ".ruff_cache/",
                "AGENTS.md",
                "CLAUDE.md",
            ]
        )

        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in self._SYNC_EVENT_TYPES:
            return

        path_str = event.src_path
        if event.event_type == "moved":
            moved_dest = getattr(event, "dest_path", None)
            if isinstance(moved_dest, str) and moved_dest:
                path_str = moved_dest
        try:
            rel_path = Path(path_str).resolve().relative_to(self.project_root)  # type: ignore[arg-type]
        except ValueError:
            return

        if not self._is_sync_relevant(rel_path):
            logger.trace("Ignoring non-sync path change: %s", rel_path)
            return

        if self.spec is not None and self.spec.match_file(str(rel_path)):
            logger.trace("Ignoring change: %s (matched .gitignore/exclude)", rel_path)
            return

        logger.info("Change detected in %s: %s", self.project_root, rel_path)
        self._trigger_sync()

    @classmethod
    def _is_sync_relevant(cls, rel_path: Path) -> bool:
        name = rel_path.name
        rel_path_str = rel_path.as_posix()
        if name.endswith("~") or name.endswith(".swp") or ".tmp." in name:
            return False
        if any(fnmatch.fnmatchcase(rel_path_str, pattern) for pattern in cls._GENERATED_SYNC_OUTPUT_GLOBS):
            return False
        if name in cls._SYNC_FILENAMES:
            return True
        parts = rel_path.parts
        return bool(parts) and parts[0] in cls._SYNC_TOP_LEVELS

    def _trigger_sync(self) -> None:
        now = time.time()
        if now - self.last_run_time < self.debounce_seconds:
            logger.debug("Skipping sync (debounce active)")
            return

        index_lock = self.project_root / ".git" / "index.lock"
        if index_lock.exists():
            self._last_git_lock_seen = now
            logger.debug("Skipping sync (git index.lock active — commit in progress)")
            return

        if now - self._last_git_lock_seen < self._GIT_COOLDOWN_S:
            logger.debug("Skipping sync (git cooldown — recent index.lock)")
            return

        self.last_run_time = now
        self._sync()

    def _sync(self) -> None:
        logger.info("Syncing artifacts for %s...", self.project_root)
        cmd = [
            "uv",
            "run",
            "--quiet",
            "--project",
            str(REPO_ROOT),
            "-m",
            "teleclaude.cli.telec",
            "sync",
            "--skip-validation",
        ]
        env = os.environ.copy()
        env["TELEC_INVOCATION_CWD"] = str(self.project_root)
        env["PWD"] = str(self.project_root)
        # Authorize the hidden, watcher-only --skip-validation flag. Live reload must
        # deploy without ever blocking on a transient mid-edit state; the commit gate is
        # the real validation contract. No other caller may set this.
        env["TELEC_DOCS_WATCHER"] = "1"

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            if result.returncode != 0:
                logger.error(
                    "Sync failed for %s (exit=%d):\n%s",
                    self.project_root,
                    result.returncode,
                    result.stderr or result.stdout,
                )
            else:
                logger.info("Sync complete for %s", self.project_root)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("Sync failed for %s: %s", self.project_root, exc)


class MultiProjectWatcher:
    """Single watcher process that tracks all registered project roots."""

    def __init__(
        self,
        *,
        observer: _ObserverProtocol | None = None,
        manifest_path: Path = PROJECTS_MANIFEST_PATH,
        refresh_interval_s: float = 15.0,
    ) -> None:
        self._observer = observer or Observer()
        self._manifest_path = manifest_path
        self._refresh_interval_s = refresh_interval_s
        self._handlers: dict[Path, SmartWatcher] = {}
        self._watches: dict[Path, ObservedWatch] = {}

    def refresh_roots(self) -> None:
        roots = {root.resolve() for root in load_roots(self._manifest_path)}

        for removed in sorted(set(self._handlers) - roots):
            watch = self._watches.pop(removed, None)
            if watch is not None:
                self._observer.unschedule(watch)
            self._handlers.pop(removed, None)
            logger.info("Stopped watching %s", removed)

        for added in sorted(roots - set(self._handlers)):
            handler = SmartWatcher(added)
            watch = self._observer.schedule(handler, str(added), recursive=True)
            self._handlers[added] = handler
            self._watches[added] = watch
            logger.info("Watching %s for changes", added)

    def run(self) -> None:
        setup_logging(source="docs-watch")
        logger.info("Starting global docs watcher (manifest=%s)", self._manifest_path)
        self.refresh_roots()
        self._observer.start()
        try:
            while True:
                time.sleep(self._refresh_interval_s)
                self.refresh_roots()
        except KeyboardInterrupt:
            self._observer.stop()
        self._observer.join()


def main() -> None:
    """Run the global watcher service."""
    MultiProjectWatcher().run()


if __name__ == "__main__":
    main()
