"""File watcher for TeleClaude artifacts."""

import fnmatch
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import InstruktAILogger, get_logger
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from teleclaude.logging_config import setup_logging

try:
    import pathspec
except ImportError:
    pathspec = None

if TYPE_CHECKING:
    from pathspec import PathSpec as PathSpecType
else:
    PathSpecType = Any

logger: InstruktAILogger = get_logger(__name__)


class SmartWatcher(FileSystemEventHandler):
    """Watch for file changes, respecting .gitignore."""

    _SYNC_EVENT_TYPES = {"created", "modified", "moved", "deleted"}
    _SYNC_TOP_LEVELS = {"docs", "agents", ".agents"}
    _SYNC_FILENAMES = {"AGENTS.master.md", "AGENTS.global.md"}
    # Generated artifacts written by `telec sync`; watching them creates self-trigger loops.
    _GENERATED_SYNC_OUTPUT_GLOBS = ("docs/**/index.yaml",)

    def __init__(self, project_root: Path, debounce_seconds: float = 2.0):
        self.project_root = project_root.resolve()
        self.debounce_seconds = debounce_seconds
        self.last_run_time = 0.0
        self.spec = self._load_gitignore()
        self._sync()  # Initial sync on start

    def _load_gitignore(self) -> PathSpecType | None:
        if not pathspec:
            logger.warning("pathspec not installed; .gitignore support disabled")
            return None

        gitignore_path = self.project_root / ".gitignore"
        patterns = []

        # Always ignore .git
        patterns.append(".git/")

        if gitignore_path.exists():
            with gitignore_path.open("r", encoding="utf-8") as f:
                patterns.extend(f.readlines())

        # Add internal ignores that might not be in gitignore but should be ignored by watcher
        patterns.extend(
            [
                "dist/",
                "__pycache__/",
                ".venv/",
                ".mypy_cache/",
                ".pytest_cache/",
                ".ruff_cache/",
                "AGENTS.md",  # Explicitly ignore generated artifacts to prevent loops
                "CLAUDE.md",
            ]
        )

        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if event.event_type not in self._SYNC_EVENT_TYPES:
            return

        # Determine relative path
        path_str = event.src_path
        if event.event_type == "moved":
            moved_dest = getattr(event, "dest_path", None)
            if isinstance(moved_dest, str) and moved_dest:
                path_str = moved_dest
        try:
            rel_path = Path(path_str).resolve().relative_to(self.project_root)
        except ValueError:
            return  # Path not in project root

        if not self._is_sync_relevant(rel_path):
            logger.trace(f"Ignoring non-sync path change: {rel_path}")
            return

        # Check against .gitignore and custom ignores
        if self.spec and self.spec.match_file(str(rel_path)):
            logger.trace(f"Ignoring change: {rel_path} (matched .gitignore/exclude)")
            return

        logger.info(f"Change detected: {rel_path}")
        self._trigger_sync()

    @classmethod
    def _is_sync_relevant(cls, rel_path: Path) -> bool:
        """Return True when a file change should trigger artifact sync."""
        name = rel_path.name
        rel_path_str = rel_path.as_posix()
        if name.endswith("~") or name.endswith(".swp") or ".tmp." in name:
            return False
        if any(fnmatch.fnmatchcase(rel_path_str, pattern) for pattern in cls._GENERATED_SYNC_OUTPUT_GLOBS):
            return False

        if name in cls._SYNC_FILENAMES:
            return True

        parts = rel_path.parts
        if not parts:
            return False

        return parts[0] in cls._SYNC_TOP_LEVELS

    def _trigger_sync(self) -> None:
        now = time.time()
        if now - self.last_run_time < self.debounce_seconds:
            logger.debug("Skipping sync (debounce active)")
            return

        # Update last run time BEFORE running to act as a naive mutex/debounce
        self.last_run_time = now
        self._sync()

    def _sync(self) -> None:
        logger.info("Syncing artifacts...")

        # Run telec sync
        cmd = [
            sys.executable,
            "-m",
            "teleclaude.cli.telec",
            "sync",
            "--warn-only",
            "--project-root",
            str(self.project_root),
        ]

        try:
            subprocess.run(cmd, cwd=self.project_root, check=False)
        except Exception as e:
            logger.error(f"Sync failed: {e}")


def run_watch(project_root: Path) -> None:
    """Run the watcher loop."""
    setup_logging()
    logger = get_logger(__name__)
    handler = SmartWatcher(project_root)
    observer = Observer()
    observer.schedule(handler, str(project_root), recursive=True)
    observer.start()

    logger.info(f"Watching {project_root} for changes (smart mode)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
