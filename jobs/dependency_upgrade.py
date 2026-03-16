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

import subprocess
import sys
import tomllib
from pathlib import Path

from instrukt_ai_logging import get_logger
from packaging.version import InvalidVersion, Version

from jobs.base import Job, JobResult

# Ensure repo root is in path for imports
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

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
    """Append [tool.uv] override-dependencies to cap major-bumped packages.

    Returns the original pyproject.toml content for later restoration.
    """
    original = pyproject_path.read_text(encoding="utf-8")

    overrides: list[str] = []
    for name, (old_ver_str, _new_ver_str) in sorted(bumps.items()):
        old_major = Version(old_ver_str).major
        cap = old_major + 1
        overrides.append(f'  "{name}<{cap}",')

    section = "\n\n[tool.uv]\noverride-dependencies = [\n" + "\n".join(overrides) + "\n]\n"
    pyproject_path.write_text(original + section, encoding="utf-8")
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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(_REPO_ROOT),
                timeout=600,
                env=env,
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
            "TELECLAUDE_ALLOW_MAIN_COMMIT": "1",
            "TELECLAUDE_ALLOW_MAIN_PUSH": "1",
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
