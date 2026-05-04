"""Tests for the release changelog generator."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.release_changelog import (
    categorize_commits,
    format_section,
    is_noise,
    load_lane_report,
    merge_lane_reports,
    parse_commitizen,
    prepend_to_changelog,
)


class TestParseCommitizen:
    def test_full_format(self) -> None:
        assert parse_commitizen("feat(cli): add new command") == ("feat", "cli", "add new command")

    def test_no_scope(self) -> None:
        assert parse_commitizen("fix: resolve crash") == ("fix", "", "resolve crash")

    def test_non_commitizen(self) -> None:
        assert parse_commitizen("Update README") is None

    def test_merge_commit(self) -> None:
        assert parse_commitizen("Merge branch 'main'") is None


class TestIsNoise:
    def test_skip_ci(self) -> None:
        assert is_noise("chore: something [skip ci]") is True

    def test_ci_skip(self) -> None:
        assert is_noise("chore: something [ci skip]") is True

    def test_todo_scaffold(self) -> None:
        assert is_noise("chore(todos): scaffold my-feature [skip ci]") is True

    def test_delivery_bookkeeping(self) -> None:
        assert is_noise("chore(my-feature): delivery bookkeeping") is True

    def test_version_bump(self) -> None:
        assert is_noise("chore: bump version to 0.5.0 [skip ci]") is True

    def test_merge(self) -> None:
        assert is_noise("Merge remote-tracking branch 'origin/main'") is True

    def test_real_feature(self) -> None:
        assert is_noise("feat(cli): add new command") is False

    def test_real_fix(self) -> None:
        assert is_noise("fix(db): resolve connection leak") is False

    def test_chore_remove(self) -> None:
        assert is_noise("chore(my-slug): remove old-thing") is True

    def test_chore_dump(self) -> None:
        assert is_noise("chore(todos): dump my-slug [skip ci]") is True


class TestCategorizeCommits:
    def test_feat_becomes_added(self) -> None:
        result = categorize_commits(["feat(cli): add todo show"])
        assert "Added" in result
        assert result["Added"] == ["**cli:** add todo show"]

    def test_fix_becomes_fixed(self) -> None:
        result = categorize_commits(["fix(db): resolve leak"])
        assert "Fixed" in result
        assert result["Fixed"] == ["**db:** resolve leak"]

    def test_refactor_becomes_changed(self) -> None:
        result = categorize_commits(["refactor(core): simplify pipeline"])
        assert "Changed" in result

    def test_chore_is_skipped(self) -> None:
        result = categorize_commits(["chore: update deps"])
        assert result == {}

    def test_noise_is_filtered(self) -> None:
        result = categorize_commits(
            [
                "feat(cli): real feature",
                "chore(todos): scaffold something [skip ci]",
                "chore: bump version to 0.5.0 [skip ci]",
                "Merge remote-tracking branch 'origin/main'",
            ]
        )
        assert len(result.get("Added", [])) == 1
        assert "Changed" not in result
        assert "Fixed" not in result

    def test_no_scope(self) -> None:
        result = categorize_commits(["feat: global feature"])
        assert result["Added"] == ["global feature"]

    def test_non_commitizen_becomes_changed(self) -> None:
        result = categorize_commits(["Restore themed markdown artifact editor"])
        assert "Changed" in result
        assert result["Changed"] == ["Restore themed markdown artifact editor"]

    def test_merge_excluded(self) -> None:
        result = categorize_commits(["Merge branch 'main'"])
        assert result == {}


class TestLoadLaneReport:
    def test_valid_report(self, tmp_path: Path) -> None:
        report = {
            "classification": "patch",
            "rationale": "Internal fixes only.",
            "contract_changes": [],
            "release_notes": "Bug fixes and improvements.",
        }
        path = tmp_path / "claude-report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        loaded = load_lane_report(path)
        assert loaded is not None
        assert loaded["classification"] == "patch"

    def test_missing_file(self, tmp_path: Path) -> None:
        assert load_lane_report(tmp_path / "nonexistent.json") is None

    def test_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        assert load_lane_report(path) is None

    def test_missing_classification(self, tmp_path: Path) -> None:
        path = tmp_path / "no-class.json"
        path.write_text(json.dumps({"rationale": "no class"}), encoding="utf-8")
        assert load_lane_report(path) is None


class TestMergeLaneReports:
    def _write_report(self, tmp_path: Path, name: str, report: dict) -> Path:
        path = tmp_path / f"{name}-report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_highlights_from_first_preferred(self, tmp_path: Path) -> None:
        claude = self._write_report(
            tmp_path,
            "claude",
            {
                "classification": "patch",
                "rationale": "r",
                "contract_changes": [],
                "release_notes": "Claude's notes",
            },
        )
        codex = self._write_report(
            tmp_path,
            "codex",
            {
                "classification": "patch",
                "rationale": "r",
                "contract_changes": [],
                "release_notes": "Codex's notes",
            },
        )
        highlights, _ = merge_lane_reports({"claude": claude, "codex": codex})
        assert highlights == "Claude's notes"

    def test_codex_fallback_when_claude_empty(self, tmp_path: Path) -> None:
        claude = self._write_report(
            tmp_path,
            "claude",
            {
                "classification": "patch",
                "rationale": "r",
                "contract_changes": [],
                "release_notes": "",
            },
        )
        codex = self._write_report(
            tmp_path,
            "codex",
            {
                "classification": "patch",
                "rationale": "r",
                "contract_changes": [],
                "release_notes": "Codex's notes",
            },
        )
        highlights, _ = merge_lane_reports({"claude": claude, "codex": codex})
        assert highlights == "Codex's notes"

    def test_contract_changes_deduplicated(self, tmp_path: Path) -> None:
        change = {"surface": "cli", "item": "todo show", "change_type": "added", "details": "New command"}
        claude = self._write_report(
            tmp_path,
            "claude",
            {
                "classification": "minor",
                "rationale": "r",
                "contract_changes": [change],
                "release_notes": "",
            },
        )
        codex = self._write_report(
            tmp_path,
            "codex",
            {
                "classification": "minor",
                "rationale": "r",
                "contract_changes": [change],
                "release_notes": "",
            },
        )
        _, cats = merge_lane_reports({"claude": claude, "codex": codex})
        assert len(cats.get("Added", [])) == 1

    def test_change_type_mapping(self, tmp_path: Path) -> None:
        claude = self._write_report(
            tmp_path,
            "claude",
            {
                "classification": "minor",
                "rationale": "r",
                "contract_changes": [
                    {"surface": "cli", "item": "new-cmd", "change_type": "added", "details": "d"},
                    {"surface": "events", "item": "old-event", "change_type": "removed", "details": "d"},
                    {"surface": "config", "item": "key", "change_type": "modified", "details": "d"},
                ],
                "release_notes": "",
            },
        )
        _, cats = merge_lane_reports({"claude": claude})
        assert "Added" in cats
        assert "Removed" in cats
        assert "Changed" in cats

    def test_missing_lane_ignored(self, tmp_path: Path) -> None:
        claude = self._write_report(
            tmp_path,
            "claude",
            {
                "classification": "patch",
                "rationale": "r",
                "contract_changes": [],
                "release_notes": "notes",
            },
        )
        highlights, _ = merge_lane_reports(
            {
                "claude": claude,
                "gemini": tmp_path / "nonexistent.json",
            }
        )
        assert highlights == "notes"


class TestFormatSection:
    def test_basic_section(self) -> None:
        result = format_section(
            version="0.5.0",
            date="2026-04-10",
            categories={"Added": ["New feature"], "Fixed": ["Bug fix"]},
        )
        assert "## [0.5.0] - 2026-04-10" in result
        assert "### Added" in result
        assert "- New feature" in result
        assert "### Fixed" in result
        assert "- Bug fix" in result

    def test_section_order(self) -> None:
        result = format_section(
            version="1.0.0",
            date="2026-01-01",
            categories={
                "Fixed": ["fix"],
                "Added": ["feature"],
                "Removed": ["old thing"],
                "Changed": ["refactor"],
            },
        )
        added_pos = result.index("### Added")
        changed_pos = result.index("### Changed")
        fixed_pos = result.index("### Fixed")
        removed_pos = result.index("### Removed")
        assert added_pos < changed_pos < fixed_pos < removed_pos

    def test_highlights(self) -> None:
        result = format_section(
            version="0.5.0",
            date="2026-04-10",
            categories={"Added": ["x"]},
            highlights="This release brings major improvements.",
        )
        assert "This release brings major improvements." in result

    def test_compare_link(self) -> None:
        result = format_section(
            version="0.5.0",
            date="2026-04-10",
            categories={"Added": ["x"]},
            compare_base="v0.4.0",
            repo_url="https://github.com/InstruktAI/TeleClaude",
        )
        assert "v0.4.0...v0.5.0" in result
        assert "https://github.com/InstruktAI/TeleClaude/compare/" in result

    def test_empty_categories_omitted(self) -> None:
        result = format_section(
            version="0.1.0",
            date="2026-01-01",
            categories={"Added": ["x"]},
        )
        assert "### Changed" not in result
        assert "### Fixed" not in result
        assert "### Removed" not in result


class TestPrependToChangelog:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        path = tmp_path / "CHANGELOG.md"
        prepend_to_changelog("## [0.1.0] - 2026-01-01\n\n### Added\n\n- Init", path)
        content = path.read_text(encoding="utf-8")
        assert "# Changelog" in content
        assert "## [0.1.0]" in content
        assert "Keep a Changelog" in content

    def test_prepends_before_existing_version(self, tmp_path: Path) -> None:
        path = tmp_path / "CHANGELOG.md"
        path.write_text(
            "# Changelog\n\nPreamble.\n\n## [0.1.0] - 2026-01-01\n\n### Added\n\n- Init\n",
            encoding="utf-8",
        )
        prepend_to_changelog("## [0.2.0] - 2026-02-01\n\n### Fixed\n\n- Bug", path)
        content = path.read_text(encoding="utf-8")
        pos_02 = content.index("## [0.2.0]")
        pos_01 = content.index("## [0.1.0]")
        assert pos_02 < pos_01
        assert "Preamble." in content
