"""Format runner — the ``telec code format`` implementation.

Dispatches per-language formatters: ruff for Python, prettier for
Markdown and TypeScript. Accepts an explicit file list (pre-commit mode)
or formats default directories (full-format mode).
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_format_tool(cmd: list[str], cwd: Path, name: str) -> None:
    """Run a format tool and raise SystemExit on failure.

    Justified subprocess: ruff, prettier have no Python API.
    """
    logger.info("Running %s", name)
    result = subprocess.run(cmd, cwd=str(cwd), check=False)
    if result.returncode != 0:
        logger.error("%s failed (exit %d)", name, result.returncode)
        raise SystemExit(result.returncode)


class FormatRunner:
    """Language-aware code formatter.

    Dispatches Python files to ruff, Markdown files to prettier.
    Accepts an explicit file list (pre-commit ``pass_filenames``) or
    auto-scopes to default directories.
    """

    def __init__(self, project_root: Path, languages: list[str]) -> None:
        self._project_root = project_root
        self._languages = languages

    def run(self, files: list[str] | None = None, *, run_all: bool = False) -> None:
        """Run formatters against the given files or default directories.

        Args:
            files: Explicit file list (pre-commit mode). None for full format.
                   Empty list is a no-op.
            run_all: When True, skip scoping and format all default
                     directories (equivalent to Makefile invocation).
        """
        if files is not None and len(files) == 0:
            return

        if run_all or files is None:
            self._format_defaults()
        else:
            self._format_files(files)

    def _format_files(self, files: list[str]) -> None:
        """Format an explicit list of files, dispatching by extension."""
        py_files = [f for f in files if f.endswith((".py", ".pyi"))]
        md_files = [f for f in files if f.endswith(".md")]
        ts_files = [f for f in files if f.endswith((".ts", ".tsx", ".js", ".jsx"))]

        if py_files:
            self._format_python(py_files)
        if md_files:
            self._format_markdown(md_files)
        if ts_files and "typescript" in self._languages:
            self._format_typescript(ts_files)

    def _format_defaults(self) -> None:
        """Format default directories based on configured languages."""
        if "python" in self._languages:
            default_dirs = ["teleclaude", "bin", "tests"]
            self._format_python(default_dirs)

        md_targets = [t for t in ["docs", "README.md", "AGENTS.md"] if (self._project_root / t).exists()]
        if md_targets:
            self._format_markdown(md_targets)

        if "typescript" in self._languages:
            self._format_typescript_defaults()

        self._cleanup_empty_claude_md()

    def _format_python(self, targets: list[str]) -> None:
        """Run ruff check --fix and ruff format on Python targets."""
        _run_format_tool(
            ["ruff", "check", "--fix", *targets],
            self._project_root,
            "ruff check --fix",
        )
        _run_format_tool(
            ["ruff", "format", *targets],
            self._project_root,
            "ruff format",
        )

    def _format_markdown(self, targets: list[str]) -> None:
        """Run prettier on Markdown targets."""
        _run_format_tool(
            ["npx", "--yes", "prettier", "--write", *targets],
            self._project_root,
            "prettier (markdown)",
        )

    def _format_typescript(self, targets: list[str]) -> None:
        """Run prettier on TypeScript targets."""
        _run_format_tool(
            ["npx", "--yes", "prettier", "--write", *targets],
            self._project_root,
            "prettier (typescript)",
        )

    def _format_typescript_defaults(self) -> None:
        """Format TypeScript defaults using frontend_root."""
        frontend_root = self._resolve_frontend_root()
        if not frontend_root.exists():
            logger.info("Frontend root %s does not exist — skipping TS format", frontend_root)
            return
        _run_format_tool(
            ["npx", "--yes", "prettier", "--write", "."],
            frontend_root,
            "prettier (typescript)",
        )

    def _resolve_frontend_root(self) -> Path:
        """Read frontend_root from teleclaude.yml, defaulting to 'frontend'."""
        import yaml

        config_path = self._project_root / "teleclaude.yml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                fr = data.get("frontend_root")
                if fr:
                    return self._project_root / str(fr)
        return self._project_root / "frontend"

    def _cleanup_empty_claude_md(self) -> None:
        """Remove empty CLAUDE.md files (agent session artifacts).

        Uses ripgrep (rg --files) which respects .gitignore and skips .venv.
        """
        try:
            result = subprocess.run(
                ["rg", "--files", "-g", "CLAUDE.md"],
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                path = self._project_root / line
                if not path.exists():
                    continue
                content = path.read_text(encoding="utf-8")
                # Strip claude-mem-context tags and whitespace
                cleaned = re.sub(r"</?claude-mem-context>", "", content).strip()
                if not cleaned:
                    path.unlink()
                    logger.info("Removed empty CLAUDE.md: %s", path)
        except FileNotFoundError:
            logger.debug("rg not found — skipping CLAUDE.md cleanup")
