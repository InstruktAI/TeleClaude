#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "instruktai-python-logger",
#     "packaging",
# ]
# ///
"""Nightly dependency upgrade job.

Tries an aggressive full upgrade first (uv lock --upgrade), validates with
lint + tests. If validation fails, falls back to a conservative strategy that
caps major-bumped packages at their previous major version, then re-resolves.

Integration:
- Called by the cron runner (scripts/cron_runner.py) on a nightly schedule.
- Config key: ``jobs.dependency_upgrade`` in teleclaude.yml.
- Commits and pushes uv.lock changes to main when validation passes.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from instrukt_ai_logging import get_logger

# Ensure repo root is in path for imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packaging.version import InvalidVersion, Version

from jobs.base import Job, JobResult, run_job_cli
from teleclaude.constants import ROLE_SYSTEM

logger = get_logger(__name__)


def _parse_lockfile_versions(path_or_bytes: Path | bytes) -> dict[str, str]:
    """Extract {package_name: version} from a uv.lock TOML file or raw bytes."""
    try:
        if isinstance(path_or_bytes, bytes):
            data = tomllib.loads(path_or_bytes.decode("utf-8"))
        else:
            data = tomllib.loads(path_or_bytes.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to parse lockfile content")
        return {}

    result: dict[str, str] = {}
    for pkg in data.get("package", []):
        name = pkg.get("name")
        version = pkg.get("version")
        if name and version:
            result[str(name)] = str(version)
    return result


def _find_major_bumps(old: dict[str, str], new: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Find packages with major version bumps between old and new lockfiles.

    Returns {name: (old_version, new_version)} for packages where the major
    version increased. New packages (not in old) are ignored.
    """
    bumps: dict[str, tuple[str, str]] = {}
    for name, new_ver_str in new.items():
        old_ver_str = old.get(name)
        if old_ver_str is None:
            continue
        try:
            old_ver = Version(old_ver_str)
            new_ver = Version(new_ver_str)
        except InvalidVersion:
            continue
        if new_ver.major > old_ver.major:
            bumps[name] = (old_ver_str, new_ver_str)
    return bumps


def _apply_conservative_caps(pyproject_path: Path, bumps: dict[str, tuple[str, str]]) -> str:
    """Write conservative override-dependencies caps into pyproject.toml.

    When [tool.uv] already exists, merges new caps with any existing
    override-dependencies rather than appending a duplicate [tool.uv] header
    (which uv rejects as a duplicate key). All existing constraints are
    preserved — same-package constraints coexist with new caps.

    Raises tomllib.TOMLDecodeError if the file is not valid TOML.
    Returns the original pyproject.toml content for later restoration.
    """
    original = pyproject_path.read_text(encoding="utf-8")

    # Build the new cap constraints for this run.
    new_caps: dict[str, str] = {}
    for name, (old_ver_str, _) in bumps.items():
        cap = Version(old_ver_str).major + 1
        new_caps[name.lower()] = f"{name}<{cap}"

    # Propagate parse errors — a malformed pyproject.toml means uv would also
    # fail, so there is nothing useful to fall back to.
    existing_overrides: list[str] = list(
        tomllib.loads(original).get("tool", {}).get("uv", {}).get("override-dependencies", [])
    )

    # Keep all existing constraints and add new caps alongside them.
    # Same-package constraints coexist (e.g. "aiohttp!=3.9.6" + "aiohttp<4").
    existing_set = set(existing_overrides)
    merged = sorted([*existing_overrides, *(cap for cap in new_caps.values() if cap not in existing_set)])

    override_block = "override-dependencies = [\n" + "\n".join(f'  "{v}",' for v in merged) + "\n]"

    # Match the exact [tool.uv] section header (not [tool.uv.anything]).
    uv_header_re = re.compile(r"^\[tool\.uv\]\s*$", re.MULTILINE)
    header_match = uv_header_re.search(original)

    if header_match is not None:
        # Scope the replacement to within the [tool.uv] section only — never
        # touch override-dependencies that belong to other tool tables.
        section_start = header_match.end()
        next_section = re.search(r"^\[", original[section_start:], re.MULTILINE)
        section_end = section_start + next_section.start() if next_section else len(original)

        uv_body = original[section_start:section_end]
        override_dep_re = re.compile(r"override-dependencies\s*=\s*\[[^\]]*\]", re.DOTALL)

        if override_dep_re.search(uv_body):
            new_body = override_dep_re.sub(override_block, uv_body, count=1)
            modified = original[:section_start] + new_body + original[section_end:]
        else:
            # Insert right after the [tool.uv] header line.
            modified = original[: header_match.end()] + f"\n{override_block}" + original[header_match.end() :]
    else:
        modified = original + f"\n\n[tool.uv]\n{override_block}\n"

    pyproject_path.write_text(modified, encoding="utf-8")
    return original


class DependencyUpgradeJob(Job):
    """Upgrade dependencies with aggressive-then-conservative fallback."""

    name = "dependency_upgrade"

    def __init__(self) -> None:
        self._lockfile_path = _REPO_ROOT / "uv.lock"
        self._pyproject_path = _REPO_ROOT / "pyproject.toml"

    def _run_command(
        self,
        cmd: list[str],
        env: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        """Execute a subprocess command. Returns (success, output)."""
        try:
            merged_env = {**os.environ, **env} if env else None
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(_REPO_ROOT),
                timeout=600,
                env=merged_env,
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "command timed out"
        except Exception as exc:
            return False, str(exc)

    def _run_validation(self) -> tuple[bool, str]:
        """Run lint and test validation. Returns (success, output)."""
        lint_ok, lint_out = self._run_command(["bash", "tools/lint.sh"])
        if not lint_ok:
            return False, f"lint failed: {lint_out}"
        test_ok, test_out = self._run_command(["bash", "tools/test.sh"])
        if not test_ok:
            return False, f"tests failed: {test_out}"
        return True, "validation passed"

    def _git_commit_and_push(self, mode: str) -> tuple[bool, str]:
        """Commit uv.lock and any lint-modified files, then push to main."""
        env_vars = {
            "TELECLAUDE_SYSTEM_ROLE": ROLE_SYSTEM,
        }

        # Stage uv.lock
        ok, out = self._run_command(["git", "add", "uv.lock"], env=env_vars)
        if not ok:
            return False, f"git add uv.lock failed: {out}"

        # Check for lint-modified files beyond uv.lock
        _ok, diff_out = self._run_command(["git", "diff", "--name-only"])
        if diff_out.strip():
            for f in diff_out.strip().splitlines():
                self._run_command(["git", "add", f.strip()], env=env_vars)

        ok, out = self._run_command(
            [
                "git",
                "commit",
                "--no-verify",
                "-m",
                f"chore(deps): {mode} dependency upgrade\n\n"
                f"\U0001f916 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)\n\n"
                f"Co-Authored-By: TeleClaude <noreply@instrukt.ai>",
            ],
            env=env_vars,
        )
        if not ok:
            return False, f"git commit failed: {out}"

        ok, out = self._run_command(["git", "push", "origin", "main"], env=env_vars)
        if not ok:
            return False, f"git push failed: {out}"

        return True, "committed and pushed"

    def run(self) -> JobResult:
        """Execute dependency upgrade with aggressive-then-conservative strategy."""
        lockfile = self._lockfile_path
        pyproject = self._pyproject_path

        if not lockfile.exists():
            return JobResult(success=False, message="uv.lock not found")

        original_lock = lockfile.read_bytes()

        # --- AGGRESSIVE UPGRADE ---
        logger.info("Starting aggressive dependency upgrade")
        ok, out = self._run_command(["uv", "lock", "--upgrade"])
        if not ok:
            lockfile.write_bytes(original_lock)
            return JobResult(success=False, message=f"uv lock --upgrade failed: {out}")

        ok, _out = self._run_command(["uv", "sync", "--frozen"])
        if not ok:
            lockfile.write_bytes(original_lock)
            return JobResult(success=False, message="uv sync failed after aggressive upgrade")

        # Check if anything changed
        new_lock = lockfile.read_bytes()
        if new_lock == original_lock:
            return JobResult(success=True, message="Dependencies unchanged, no upgrade needed")

        # Validate aggressive upgrade
        valid, validation_msg = self._run_validation()
        if valid:
            ok, push_msg = self._git_commit_and_push("aggressive")
            if ok:
                return JobResult(success=True, message="Aggressive upgrade succeeded")
            lockfile.write_bytes(original_lock)
            return JobResult(success=False, message=f"Aggressive upgrade passed but push failed: {push_msg}")

        # --- CONSERVATIVE FALLBACK ---
        logger.info("Aggressive upgrade failed validation, trying conservative fallback")

        old_versions = _parse_lockfile_versions(original_lock)
        new_versions = _parse_lockfile_versions(lockfile)
        bumps = _find_major_bumps(old_versions, new_versions)

        if not bumps:
            logger.info("No major bumps found — nothing to cap, both tiers failed")
            lockfile.write_bytes(original_lock)
            return JobResult(
                success=False,
                message=f"Aggressive upgrade failed validation and no major bumps to cap: {validation_msg}",
            )

        logger.info("Major bumps found: %s", ", ".join(f"{k} {v[0]}->{v[1]}" for k, v in bumps.items()))

        # Restore original lockfile before conservative re-resolve
        lockfile.write_bytes(original_lock)

        # Apply caps to pyproject.toml
        original_pyproject = _apply_conservative_caps(pyproject, bumps)
        try:
            ok, out = self._run_command(["uv", "lock", "--upgrade"])
            if not ok:
                lockfile.write_bytes(original_lock)
                return JobResult(success=False, message=f"Conservative uv lock failed: {out}")

            ok, _out = self._run_command(["uv", "sync", "--frozen"])
            if not ok:
                lockfile.write_bytes(original_lock)
                return JobResult(success=False, message="Conservative uv sync failed")

            valid, validation_msg = self._run_validation()
            if valid:
                # Restore pyproject.toml before committing
                pyproject.write_text(original_pyproject, encoding="utf-8")
                ok, push_msg = self._git_commit_and_push("conservative")
                if ok:
                    return JobResult(
                        success=True,
                        message=f"Conservative upgrade succeeded (capped: {', '.join(bumps.keys())})",
                    )
                lockfile.write_bytes(original_lock)
                return JobResult(success=False, message=f"Conservative upgrade passed but push failed: {push_msg}")

            lockfile.write_bytes(original_lock)
            return JobResult(success=False, message=f"Conservative upgrade also failed validation: {validation_msg}")
        finally:
            # Always restore pyproject.toml
            pyproject.write_text(original_pyproject, encoding="utf-8")


JOB = DependencyUpgradeJob()


if __name__ == "__main__":
    raise SystemExit(run_job_cli(JOB))
