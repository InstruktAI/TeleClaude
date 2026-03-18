"""Prepare Quality cartridge — assesses DOR quality for todo lifecycle events."""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict
from teleclaude.core.next_machine._types import StateValue
from teleclaude.events.envelope import EventEnvelope, EventLevel, EventVisibility
from teleclaude.events.pipeline import PipelineContext
from teleclaude.events.producer import emit_event

logger = get_logger(__name__)

_PLANNING_PREFIX = "domain.software-development.planning."

_TRIGGER_EVENTS = {
    "domain.software-development.planning.artifact_changed",
    "domain.software-development.planning.todo_created",
    "domain.software-development.planning.todo_dumped",
    "domain.software-development.planning.todo_activated",
    "domain.software-development.planning.dependency_resolved",
}


class RequirementsScoreResult(TypedDict):
    """Score breakdown for the requirements artifact."""

    dimensions: dict[str, int]
    gaps: list[str]
    raw: int
    max: int


class PlanScoreResult(TypedDict):
    """Score breakdown for the implementation-plan artifact."""

    dimensions: dict[str, int]
    gaps: list[str]
    contradictions: list[str]
    raw: int
    max: int


@dataclass(frozen=True)
class DorArtifacts:
    """Loaded planning artifacts and their paths for one todo."""

    req_path: Path
    plan_path: Path
    roadmap_path: Path
    req_content: str
    plan_content: str


class DorReportData(TypedDict):
    """Rendered DOR assessment details persisted to disk and events."""

    slug: str
    score: int
    verdict: str
    req_result: RequirementsScoreResult
    plan_result: PlanScoreResult
    edits: list[str]
    assessed_at: str
    assessed_commit: str


@dataclass(frozen=True)
class AssessmentOutcome:
    """Completed DOR assessment payload."""

    report: DorReportData
    all_gaps: list[str]


# ── DOR Scorer ────────────────────────────────────────────────────────────────


def _has_section(content: str, *patterns: str) -> bool:
    """Return whether any heading-style pattern appears in the content."""
    for pat in patterns:
        if re.search(pat, content, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def _count_fr_sections(content: str) -> int:
    """Count functional requirement section headings."""
    return len(re.findall(r"^#+\s+FR\d+", content, re.MULTILINE))


def _count_checkboxes(content: str) -> int:
    """Count Markdown task checkboxes."""
    return len(re.findall(r"^\s*-\s+\[[ x]\]", content, re.MULTILINE))


def score_requirements(content: str) -> RequirementsScoreResult:
    """Score requirements.md against DOR rubric. Returns scores and gaps."""
    dims: dict[str, int] = {}
    gaps: list[str] = []

    # Intent clarity (0-2)
    has_goal = _has_section(content, r"^#+\s+(Goal|Overview|Purpose|Objective|What)")
    has_outcome = _has_section(content, r"^#+\s+(Acceptance|Success|Expected|Criteria)")
    dims["intent_clarity"] = (1 if has_goal else 0) + (1 if has_outcome else 0)
    if not has_goal:
        gaps.append("requirements: missing Goal/Overview section")
    if not has_outcome:
        gaps.append("requirements: missing Acceptance Criteria / Success Criteria section")

    # Scope atomicity (0-2)
    has_scope = _has_section(content, r"^#+\s+Scope")
    has_in_out = _has_section(content, r"In scope|Out of scope|In-scope|Out-of-scope")
    dims["scope_atomicity"] = (1 if has_scope else 0) + (1 if has_in_out else 0)
    if not has_scope:
        gaps.append("requirements: missing Scope section")
    if not has_in_out:
        gaps.append("requirements: missing in-scope / out-of-scope delineation")

    # Success criteria (0-2)
    fr_count = _count_fr_sections(content)
    has_fr = fr_count >= 2
    has_ac = _has_section(content, r"^#+\s+Acceptance")
    dims["success_criteria"] = (1 if has_fr else 0) + (1 if has_ac else 0)
    if not has_fr:
        gaps.append("requirements: fewer than 2 functional requirements (FR) sections")
    if not has_ac:
        gaps.append("requirements: no Acceptance Criteria section")

    # Dependency correctness (0-1)
    has_dep = _has_section(content, r"^#+\s+(Depend|Prerequisite|Prior)")
    dims["dependency_correctness"] = 1 if has_dep else 0
    if not has_dep:
        gaps.append("requirements: missing Dependency / Prerequisites section")

    # Constraint specificity (0-1)
    has_constraints = _has_section(content, r"^#+\s+(Constraint|Non-functional|NFR|Limitation)")
    dims["constraint_specificity"] = 1 if has_constraints else 0
    if not has_constraints:
        gaps.append("requirements: missing Constraints / Non-functional requirements section")

    return {"dimensions": dims, "gaps": gaps, "raw": sum(dims.values()), "max": 8}


def score_plan(content: str, requirements: str) -> PlanScoreResult:
    """Score implementation-plan.md against DOR rubric. Returns scores and gaps."""
    dims: dict[str, int] = {}
    gaps: list[str] = []
    contradictions = _find_plan_requirement_contradictions(content, requirements)

    dims["concrete_file_targets"], section_gaps = _score_plan_file_targets(content)
    gaps.extend(section_gaps)
    dims["verification_steps"], section_gaps = _score_plan_verification(content)
    gaps.extend(section_gaps)
    dims["risk_identification"], section_gaps = _score_plan_risks(content)
    gaps.extend(section_gaps)
    dims["task_requirement_traceability"], section_gaps = _score_plan_traceability(content)
    gaps.extend(section_gaps)

    dims["plan_requirement_consistency"] = 0 if contradictions else 1
    if contradictions:
        gaps.extend([f"contradiction: {c}" for c in contradictions])

    return {
        "dimensions": dims,
        "gaps": gaps,
        "contradictions": contradictions,
        "raw": sum(dims.values()),
        "max": 8,
    }


def _score_plan_file_targets(content: str) -> tuple[int, list[str]]:
    """Score whether the plan points at concrete files and project paths."""
    gaps: list[str] = []
    file_refs = len(re.findall(r"`[^`]+\.(py|ts|js|yaml|yml|json|md|sh|toml)`", content))
    has_file_refs = file_refs >= 3
    has_paths = bool(re.search(r"teleclaude[_/]|tests/|src/|lib/", content))
    if not has_file_refs:
        gaps.append("plan: fewer than 3 explicit file references with extensions")
    if not has_paths:
        gaps.append("plan: no recognisable directory path references")
    return (1 if has_file_refs else 0) + (1 if has_paths else 0), gaps


def _score_plan_verification(content: str) -> tuple[int, list[str]]:
    """Score whether the plan contains verification steps and task checkboxes."""
    gaps: list[str] = []
    has_verification = _has_section(content, r"\*\*Verification\*\*|## Verification|verification:")
    has_tasks = _count_checkboxes(content) >= 3
    if not has_verification:
        gaps.append("plan: missing **Verification:** steps in task sections")
    if not has_tasks:
        gaps.append("plan: fewer than 3 task checkboxes")
    return (1 if has_verification else 0) + (1 if has_tasks else 0), gaps


def _score_plan_risks(content: str) -> tuple[int, list[str]]:
    """Score whether the plan names risks or mitigations."""
    has_risks = _has_section(content, r"^#+\s+Risk|^#+\s+Mitigation")
    gaps = [] if has_risks else ["plan: missing Risks section"]
    return (1 if has_risks else 0), gaps


def _score_plan_traceability(content: str) -> tuple[int, list[str]]:
    """Score task structure and links back to functional requirements."""
    gaps: list[str] = []
    has_fr_refs = len(re.findall(r"\bFR\d+\b", content)) >= 2
    has_phases = _has_section(content, r"^#+\s+Phase \d|^#+\s+Task \d")
    if not has_fr_refs:
        gaps.append("plan: fewer than 2 explicit FR references")
    if not has_phases:
        gaps.append("plan: no Phase or Task section headers")
    return (1 if has_fr_refs else 0) + (1 if has_phases else 0), gaps


def _find_plan_requirement_contradictions(content: str, requirements: str) -> list[str]:
    """Return obvious wording contradictions between plan and requirements."""
    contradictions: list[str] = []
    plan_lower = content.lower()
    req_lower = requirements.lower()
    contradiction_pairs = [
        ("copy ", "reuse "),
        ("create new", "extend existing"),
        ("replace", "extend"),
    ]
    for plan_word, req_word in contradiction_pairs:
        if plan_word in plan_lower and req_word in req_lower and plan_word not in req_lower:
            contradictions.append(f"plan uses '{plan_word.strip()}' but requirements says '{req_word.strip()}'")
    return contradictions


def compute_dor_score(req_result: RequirementsScoreResult, plan_result: PlanScoreResult) -> tuple[int, str]:
    """Combine scores and return (normalized_score_1_10, verdict).

    Returns 'pass' when score >= 8, 'needs_work' otherwise. Callers that have
    run the gap-filler and found no improvements should override verdict to
    'needs_decision' themselves, since exhaustion is not observable here.
    """
    total_raw = req_result["raw"] + plan_result["raw"]
    max_raw = req_result["max"] + plan_result["max"]  # 16

    # Normalize to 1-10
    score = max(1, round(1 + (total_raw / max_raw) * 9))

    verdict = "pass" if score >= 8 else "needs_work"

    return score, verdict


# ── Structural Gap Filler ─────────────────────────────────────────────────────


def _fill_requirements_gaps(
    req_content: str,
    gaps: list[str],
    roadmap_path: Path,
    slug: str,
) -> tuple[str, list[str]]:
    """Fill structural gaps in requirements.md. Returns (updated_content, edits_made)."""
    edits: list[str] = []
    content = req_content

    if "missing Dependency" in " ".join(gaps) and not _has_section(content, r"^#+\s+(Depend|Prerequisite|Prior)"):
        dep_text = _build_dependency_section(roadmap_path, slug)
        if dep_text:
            content = content.rstrip() + f"\n\n{dep_text}\n"
            edits.append("added Dependency section from roadmap.yaml")

    if "missing Constraints" in " ".join(gaps) and not _has_section(content, r"^#+\s+(Constraint|Non-functional|NFR)"):
        content = content.rstrip() + "\n\n## Constraints\n\n<!-- TODO: specify constraints -->\n"
        edits.append("flagged missing Constraints section (placeholder added)")

    return content, edits


def _build_dependency_section(roadmap_path: Path, slug: str) -> str:
    """Build a dependency section from roadmap metadata for the given todo slug."""
    if not roadmap_path.exists():
        return ""
    try:
        raw = yaml.safe_load(roadmap_path.read_text()) or []
    except (yaml.YAMLError, OSError):
        return ""
    if not isinstance(raw, list) or not raw:
        return ""
    entry = next((item for item in raw if isinstance(item, dict) and item.get("slug") == slug), None)
    if entry is None:
        return ""
    deps = [str(d) for d in entry.get("deps", []) if d]
    if not deps:
        return ""
    lines = ["## Dependency", "", "Prerequisites (from roadmap.yaml):"]
    for d in deps:
        lines.append(f"- `{d}`")
    return "\n".join(lines)


def _fill_plan_gaps(plan_content: str, gaps: list[str]) -> tuple[str, list[str]]:
    """Fill structural gaps in implementation-plan.md. Returns (updated_content, edits_made)."""
    edits: list[str] = []
    content = plan_content

    # Add verification placeholders for task sections missing them
    if "missing **Verification:**" in " ".join(gaps):
        lines = content.split("\n")
        new_lines: list[str] = []
        in_task = False
        task_header_re = re.compile(r"^#{2,4}\s+Task \d+\.\d+")
        next_header_re = re.compile(r"^#{1,4}\s+")
        pending_verify = False
        for line in lines:
            if task_header_re.match(line):
                in_task = True
                pending_verify = True
                new_lines.append(line)
                continue
            if in_task and next_header_re.match(line) and not task_header_re.match(line):
                # Closing out a task section — add verification if missing
                if pending_verify:
                    new_lines.append("\n**Verification:** TBD\n")
                    edits.append("added Verification placeholder to task section")
                    pending_verify = False
                in_task = task_header_re.match(line) is not None
            elif in_task and "**Verification:**" in line:
                pending_verify = False
            new_lines.append(line)
        if pending_verify:
            new_lines.append("\n**Verification:** TBD\n")
            edits.append("added Verification placeholder to final task section")
        content = "\n".join(new_lines)

    if "missing Risks" in " ".join(gaps) and not _has_section(content, r"^#+\s+Risk"):
        content = content.rstrip() + "\n\n## Risks\n\n<!-- TODO: identify risks -->\n"
        edits.append("flagged missing Risks section (placeholder added)")

    return content, edits


# ── State & Report I/O ────────────────────────────────────────────────────────


def _get_todo_commit(slug: str, project_root: Path) -> str:
    """Get short git commit hash for the todo folder.

    Returns 'unknown' on failure; callers must not treat consecutive 'unknown'
    values as idempotency evidence (see _assess idempotency guard).
    """
    todo_path = f"todos/{slug}/"
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", todo_path],
            capture_output=True,
            check=False,
            text=True,
            cwd=project_root,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        logger.warning("prepare-quality: git log failed for todo", slug=slug)
        return "unknown"


def _read_state_yaml(state_path: Path) -> dict[str, StateValue]:
    """Read and parse `state.yaml`, returning an empty state when absent."""
    if not state_path.exists():
        return {}
    try:
        return cast(dict[str, StateValue], yaml.safe_load(state_path.read_text()) or {})
    except (yaml.YAMLError, OSError):
        logger.error("prepare-quality: corrupt state.yaml, cannot read", path=str(state_path))
        raise


def _write_state_yaml(state_path: Path, state: dict[str, StateValue]) -> None:
    """Write the todo state YAML back to disk."""
    state_path.write_text(yaml.safe_dump(state, default_flow_style=False, sort_keys=False))


def _write_dor_report(report_path: Path, report: DorReportData) -> None:
    """Write the Markdown DOR assessment report for a todo."""
    all_gaps = report["req_result"]["gaps"] + report["plan_result"]["gaps"]
    lines = [
        f"# DOR Assessment: {report['slug']}",
        "",
        f"**Score:** {report['score']}/10  **Verdict:** `{report['verdict']}`",
        f"**Assessed at:** {report['assessed_at']}  **Commit:** `{report['assessed_commit']}`",
        "",
        "## Per-dimension scores",
        "",
        "### Requirements",
    ]
    for dim, val in report["req_result"]["dimensions"].items():
        lines.append(f"- {dim}: {val}")
    lines += ["", "### Implementation Plan"]
    for dim, val in report["plan_result"]["dimensions"].items():
        lines.append(f"- {dim}: {val}")

    if report["edits"]:
        lines += ["", "## Edits performed", ""]
        for edit in report["edits"]:
            lines.append(f"- {edit}")

    if all_gaps:
        lines += ["", "## Remaining gaps", ""]
        for gap in all_gaps:
            lines.append(f"- {gap}")
    else:
        lines += ["", "## Remaining gaps", "", "None."]

    if report["verdict"] == "needs_decision":
        blockers = [g for g in all_gaps if "contradiction" in g or "decision" in g]
        if not blockers:
            blockers = all_gaps[:3]
        lines += ["", "## Decisions needed", ""]
        for b in blockers:
            lines.append(f"- {b}")

    report_path.write_text("\n".join(lines) + "\n")


# ── Cartridge ─────────────────────────────────────────────────────────────────


def _find_project_root() -> Path:
    """Walk up from cwd to find the project root (where todos/ lives)."""
    here = Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "todos").is_dir():
            return candidate
    logger.warning("prepare-quality: no todos/ directory found, falling back to cwd", cwd=str(here))
    return here


def _get_dor_state(state: dict[str, StateValue]) -> dict[str, StateValue]:
    """Return the stored DOR state mapping when present."""
    dor_state = state.get("dor", {})
    return cast(dict[str, StateValue], dor_state if isinstance(dor_state, dict) else {})


def _is_current_pass(state: dict[str, StateValue], current_commit: str) -> bool:
    """Return whether the todo already passed assessment at the current commit."""
    dor_state = _get_dor_state(state)
    return (
        current_commit != "unknown"
        and dor_state.get("assessed_commit") == current_commit
        and dor_state.get("status") == "pass"
    )


def _load_dor_artifacts(todo_dir: Path, project_root: Path) -> DorArtifacts | None:
    """Read planning artifacts for a todo, or return `None` when absent."""
    req_path = todo_dir / "requirements.md"
    plan_path = todo_dir / "implementation-plan.md"
    roadmap_path = project_root / "todos" / "roadmap.yaml"
    req_content = req_path.read_text() if req_path.exists() else ""
    plan_content = plan_path.read_text() if plan_path.exists() else ""
    if not req_content and not plan_content:
        return None
    return DorArtifacts(
        req_path=req_path,
        plan_path=plan_path,
        roadmap_path=roadmap_path,
        req_content=req_content,
        plan_content=plan_content,
    )


async def _claim_quality_notification(context: PipelineContext, slug: str) -> int | None:
    """Claim the existing notification for a todo assessment run."""
    notification = await context.db.find_by_group_key("slug", slug)
    notification_id: int | None = notification["id"] if notification else None
    if notification_id is not None:
        await context.db.update_agent_status(notification_id, "claimed", "prepare-quality-runner")
    return notification_id


def _score_artifacts(req_content: str, plan_content: str) -> tuple[RequirementsScoreResult, PlanScoreResult, int, str]:
    """Return requirement score, plan score, normalized score, and verdict."""
    req_result = score_requirements(req_content)
    plan_result = score_plan(plan_content, req_content)
    score, verdict = compute_dor_score(req_result, plan_result)
    return req_result, plan_result, score, verdict


def _apply_structural_improvements(
    artifacts: DorArtifacts,
    req_result: RequirementsScoreResult,
    plan_result: PlanScoreResult,
    slug: str,
) -> tuple[str, str, list[str]]:
    """Fill lightweight structural gaps and persist changed artifacts."""
    req_content = artifacts.req_content
    plan_content = artifacts.plan_content
    all_edits: list[str] = []

    new_req, req_edits = _fill_requirements_gaps(req_content, req_result["gaps"], artifacts.roadmap_path, slug)
    if req_edits and new_req != req_content:
        artifacts.req_path.write_text(new_req)
        all_edits.extend(req_edits)
        req_content = new_req

    new_plan, plan_edits = _fill_plan_gaps(plan_content, plan_result["gaps"])
    if plan_edits and new_plan != plan_content:
        artifacts.plan_path.write_text(new_plan)
        all_edits.extend(plan_edits)
        plan_content = new_plan

    return req_content, plan_content, all_edits


def _build_assessment_outcome(artifacts: DorArtifacts, slug: str, current_commit: str) -> AssessmentOutcome:
    """Run scoring, optional improvements, and prepare the persisted report payload."""
    req_result, plan_result, score, verdict = _score_artifacts(artifacts.req_content, artifacts.plan_content)
    req_content = artifacts.req_content
    plan_content = artifacts.plan_content
    all_edits: list[str] = []

    if score < 8:
        req_content, plan_content, all_edits = _apply_structural_improvements(artifacts, req_result, plan_result, slug)
        if all_edits:
            req_result, plan_result, score, verdict = _score_artifacts(req_content, plan_content)
        else:
            verdict = "needs_decision"

    report = DorReportData(
        slug=slug,
        score=score,
        verdict=verdict,
        req_result=req_result,
        plan_result=plan_result,
        edits=all_edits,
        assessed_at=datetime.now(UTC).isoformat(),
        assessed_commit=current_commit,
    )
    return AssessmentOutcome(report=report, all_gaps=req_result["gaps"] + plan_result["gaps"])


def _write_dor_state(
    state_path: Path,
    state: dict[str, StateValue],
    report: DorReportData,
    all_gaps: list[str],
) -> None:
    """Persist the assessment summary back into `state.yaml`."""
    state["dor"] = cast(
        StateValue,
        {
            "last_assessed_at": report["assessed_at"],
            "score": report["score"],
            "status": report["verdict"],
            "schema_version": 1,
            "blockers": all_gaps[:10],
            "actions_taken": {
                "requirements_updated": any("requirements" in edit for edit in report["edits"]),
                "implementation_plan_updated": any("plan" in edit.lower() for edit in report["edits"]),
            },
            "assessed_commit": report["assessed_commit"],
        },
    )
    _write_state_yaml(state_path, state)


async def _finalize_notification(
    context: PipelineContext,
    notification_id: int | None,
    slug: str,
    report: DorReportData,
    all_gaps: list[str],
) -> None:
    """Resolve the assessment notification when appropriate."""
    if notification_id is None:
        return
    if report["verdict"] in ("pass", "needs_work"):
        await context.db.resolve_notification(
            notification_id,
            cast(
                JsonDict,
                {"verdict": report["verdict"], "score": report["score"], "assessed_by": "prepare-quality-runner"},
            ),
        )
        return
    logger.info(
        "prepare-quality: needs_decision — leaving notification unresolved",
        slug=slug,
        blockers=all_gaps[:5],
    )


async def _emit_dor_assessed_event(slug: str, report: DorReportData) -> None:
    """Emit the DOR assessment event when the producer is configured."""
    try:
        await emit_event(
            event="domain.software-development.planning.dor_assessed",
            source="prepare-quality-runner",
            level=EventLevel.WORKFLOW,
            domain="software-development",
            visibility=EventVisibility.LOCAL,
            entity=slug,
            description=f"DOR assessed for {slug}: {report['verdict']} (score {report['score']}/10)",
            payload=cast(
                JsonDict,
                {
                    "slug": slug,
                    "score": report["score"],
                    "verdict": report["verdict"],
                    "assessed_commit": report["assessed_commit"],
                },
            ),
        )
    except RuntimeError:
        logger.debug("prepare-quality: producer not configured, skipping dor_assessed emit", slug=slug)


class PrepareQualityCartridge:
    """Assess DOR quality for planning artifacts and emit the assessment event."""

    name = "prepare-quality"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        """Handle planning events that should trigger a DOR assessment."""
        # Pass through non-planning events immediately
        if not event.event.startswith(_PLANNING_PREFIX):
            return event
        if event.event not in _TRIGGER_EVENTS:
            return event

        slug = event.payload.get("slug")
        if not slug:
            logger.warning("prepare-quality: event missing slug, skipping", event=event.event)
            return event

        start = time.monotonic()
        try:
            await self._assess(slug, event, context)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("prepare-quality: assessment failed", slug=slug, event=event.event)
        elapsed = time.monotonic() - start
        if elapsed > 2.0:
            logger.warning("prepare-quality: assessment took >2s", slug=slug, elapsed_s=round(elapsed, 2))

        return event

    def identifier(self) -> str:
        """Return the stable cartridge identifier."""
        return self.name

    async def _assess(
        self,
        slug: str,
        _event: EventEnvelope,
        context: PipelineContext,
    ) -> None:
        """Run the full DOR assessment workflow for one todo slug."""
        project_root = _find_project_root()
        todo_dir = project_root / "todos" / slug

        if _is_slug_delivered_or_frozen(slug, project_root):
            logger.debug("prepare-quality: slug is delivered/frozen, skipping", slug=slug)
            return

        state_path = todo_dir / "state.yaml"
        state = _read_state_yaml(state_path)
        current_commit = await asyncio.to_thread(_get_todo_commit, slug, project_root)
        if _is_current_pass(state, current_commit):
            logger.debug(
                "prepare-quality: already assessed at commit, skipping",
                slug=slug,
                commit=current_commit,
            )
            return

        artifacts = _load_dor_artifacts(todo_dir, project_root)
        if artifacts is None:
            logger.info("prepare-quality: no artifacts to assess", slug=slug)
            return

        notification_id = await _claim_quality_notification(context, slug)
        outcome = _build_assessment_outcome(artifacts, slug, current_commit)
        _write_dor_report(todo_dir / "dor-report.md", outcome.report)
        _write_dor_state(state_path, state, outcome.report, outcome.all_gaps)

        logger.info(
            "prepare-quality: assessment complete",
            slug=slug,
            score=outcome.report["score"],
            verdict=outcome.report["verdict"],
            edits=len(outcome.report["edits"]),
        )
        await _finalize_notification(context, notification_id, slug, outcome.report, outcome.all_gaps)
        await _emit_dor_assessed_event(slug, outcome.report)


def _is_slug_delivered_or_frozen(slug: str, project_root: Path) -> bool:
    """Return whether the slug already lives in delivered or icebox state."""
    delivered_path = project_root / "todos" / "delivered.yaml"
    if delivered_path.exists():
        try:
            items = yaml.safe_load(delivered_path.read_text()) or []
            if any(item.get("slug") == slug for item in items if isinstance(item, dict)):
                return True
        except (yaml.YAMLError, OSError):
            logger.warning("prepare-quality: cannot read delivered.yaml", path=str(delivered_path))

    icebox_path = project_root / "todos" / "_icebox" / "icebox.yaml"
    if icebox_path.exists():
        try:
            items = yaml.safe_load(icebox_path.read_text()) or []
            if any(item.get("slug") == slug for item in items if isinstance(item, dict)):
                return True
        except (yaml.YAMLError, OSError):
            logger.warning("prepare-quality: cannot read icebox.yaml", path=str(icebox_path))

    icebox_md = project_root / "todos" / "icebox.md"
    if icebox_md.exists():
        try:
            content = icebox_md.read_text()
            if re.search(rf"\b{re.escape(slug)}\b", content):
                return True
        except OSError:
            logger.warning("prepare-quality: cannot read icebox.md", path=str(icebox_md))

    return False
