"""Prepare Quality cartridge — assesses DOR quality for todo lifecycle events."""

from __future__ import annotations

import asyncio
import re
import time
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
    dimensions: dict[str, int]
    gaps: list[str]
    raw: int
    max: int


class PlanScoreResult(TypedDict):
    dimensions: dict[str, int]
    gaps: list[str]
    contradictions: list[str]
    raw: int
    max: int


# ── DOR Scorer ────────────────────────────────────────────────────────────────


def _has_section(content: str, *patterns: str) -> bool:
    for pat in patterns:
        if re.search(pat, content, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def _count_fr_sections(content: str) -> int:
    return len(re.findall(r"^#+\s+FR\d+", content, re.MULTILINE))


def _count_checkboxes(content: str) -> int:
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
    contradictions: list[str] = []

    # Concrete file targets (0-2)
    file_refs = len(re.findall(r"`[^`]+\.(py|ts|js|yaml|yml|json|md|sh|toml)`", content))
    has_file_refs = file_refs >= 3
    has_paths = bool(re.search(r"teleclaude[_/]|tests/|src/|lib/", content))
    dims["concrete_file_targets"] = (1 if has_file_refs else 0) + (1 if has_paths else 0)
    if not has_file_refs:
        gaps.append("plan: fewer than 3 explicit file references with extensions")
    if not has_paths:
        gaps.append("plan: no recognisable directory path references")

    # Verification steps (0-2)
    has_verification = _has_section(content, r"\*\*Verification\*\*|## Verification|verification:")
    task_count = _count_checkboxes(content)
    has_tasks = task_count >= 3
    dims["verification_steps"] = (1 if has_verification else 0) + (1 if has_tasks else 0)
    if not has_verification:
        gaps.append("plan: missing **Verification:** steps in task sections")
    if not has_tasks:
        gaps.append("plan: fewer than 3 task checkboxes")

    # Risk identification (0-1)
    has_risks = _has_section(content, r"^#+\s+Risk|^#+\s+Mitigation")
    dims["risk_identification"] = 1 if has_risks else 0
    if not has_risks:
        gaps.append("plan: missing Risks section")

    # Task-to-requirement traceability (0-2)
    fr_refs = len(re.findall(r"\bFR\d+\b", content))
    has_fr_refs = fr_refs >= 2
    has_phases = _has_section(content, r"^#+\s+Phase \d|^#+\s+Task \d")
    dims["task_requirement_traceability"] = (1 if has_fr_refs else 0) + (1 if has_phases else 0)
    if not has_fr_refs:
        gaps.append("plan: fewer than 2 explicit FR references")
    if not has_phases:
        gaps.append("plan: no Phase or Task section headers")

    # Plan-requirement consistency (0-1)
    # Check for obvious contradictions: plan says "copy" but req says "reuse", etc.
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
    import subprocess

    todo_path = f"todos/{slug}/"
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", todo_path],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        logger.warning("prepare-quality: git log failed for todo", slug=slug)
        return "unknown"


def _read_state_yaml(state_path: Path) -> dict[str, StateValue]:
    if not state_path.exists():
        return {}
    try:
        return cast(dict[str, StateValue], yaml.safe_load(state_path.read_text()) or {})
    except (yaml.YAMLError, OSError):
        logger.error("prepare-quality: corrupt state.yaml, cannot read", path=str(state_path))
        raise


def _write_state_yaml(state_path: Path, state: dict[str, StateValue]) -> None:
    state_path.write_text(yaml.safe_dump(state, default_flow_style=False, sort_keys=False))


def _write_dor_report(
    report_path: Path,
    slug: str,
    score: int,
    verdict: str,
    req_result: RequirementsScoreResult,
    plan_result: PlanScoreResult,
    edits: list[str],
    assessed_at: str,
    assessed_commit: str,
) -> None:
    all_gaps = req_result["gaps"] + plan_result["gaps"]
    lines = [
        f"# DOR Assessment: {slug}",
        "",
        f"**Score:** {score}/10  **Verdict:** `{verdict}`",
        f"**Assessed at:** {assessed_at}  **Commit:** `{assessed_commit}`",
        "",
        "## Per-dimension scores",
        "",
        "### Requirements",
    ]
    for dim, val in req_result["dimensions"].items():
        lines.append(f"- {dim}: {val}")
    lines += ["", "### Implementation Plan"]
    for dim, val in plan_result["dimensions"].items():
        lines.append(f"- {dim}: {val}")

    if edits:
        lines += ["", "## Edits performed", ""]
        for edit in edits:
            lines.append(f"- {edit}")

    if all_gaps:
        lines += ["", "## Remaining gaps", ""]
        for gap in all_gaps:
            lines.append(f"- {gap}")
    else:
        lines += ["", "## Remaining gaps", "", "None."]

    if verdict == "needs_decision":
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


class PrepareQualityCartridge:
    name = "prepare-quality"

    async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
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
            await self._assess(slug, event, context)  # type: ignore[arg-type]
        except Exception:
            logger.exception("prepare-quality: assessment failed", slug=slug, event=event.event)
        elapsed = time.monotonic() - start
        if elapsed > 2.0:
            logger.warning("prepare-quality: assessment took >2s", slug=slug, elapsed_s=round(elapsed, 2))

        return event

    async def _assess(self, slug: str, _event: EventEnvelope, context: PipelineContext) -> None:
        project_root = _find_project_root()
        todo_dir = project_root / "todos" / slug

        # Skip delivered/icebox slugs
        if _is_slug_delivered_or_frozen(slug, project_root):
            logger.debug("prepare-quality: slug is delivered/frozen, skipping", slug=slug)
            return

        state_path = todo_dir / "state.yaml"
        state = _read_state_yaml(state_path)

        current_commit = await asyncio.to_thread(_get_todo_commit, slug, project_root)
        dor_state_raw = state.get("dor", {})
        dor_state = dor_state_raw if isinstance(dor_state_raw, dict) else {}
        if (
            current_commit != "unknown"
            and dor_state.get("assessed_commit") == current_commit
            and dor_state.get("status") == "pass"
        ):
            logger.debug(
                "prepare-quality: already assessed at commit, skipping",
                slug=slug,
                commit=current_commit,
            )
            return

        # Read artifacts before claiming — keeps early returns side-effect free
        req_path = todo_dir / "requirements.md"
        plan_path = todo_dir / "implementation-plan.md"
        roadmap_path = project_root / "todos" / "roadmap.yaml"

        req_content = req_path.read_text() if req_path.exists() else ""
        plan_content = plan_path.read_text() if plan_path.exists() else ""

        if not req_content and not plan_content:
            logger.info("prepare-quality: no artifacts to assess", slug=slug)
            return

        # Claim notification only when there is actual work to do
        notification = await context.db.find_by_group_key("slug", slug)
        notification_id: int | None = notification["id"] if notification else None
        if notification_id is not None:
            await context.db.update_agent_status(notification_id, "claimed", "prepare-quality-runner")

        # Score
        req_result = score_requirements(req_content)
        plan_result = score_plan(plan_content, req_content)
        score, verdict = compute_dor_score(req_result, plan_result)

        all_edits: list[str] = []

        # Lightweight improvement when below threshold
        if score < 8:
            new_req, req_edits = _fill_requirements_gaps(req_content, req_result["gaps"], roadmap_path, slug)
            if req_edits and new_req != req_content:
                req_path.write_text(new_req)
                all_edits.extend(req_edits)
                req_content = new_req

            new_plan, plan_edits = _fill_plan_gaps(plan_content, plan_result["gaps"])
            if plan_edits and new_plan != plan_content:
                plan_path.write_text(new_plan)
                all_edits.extend(plan_edits)
                plan_content = new_plan

            # Reassess after improvements
            if all_edits:
                req_result = score_requirements(req_content)
                plan_result = score_plan(plan_content, req_content)
                score, verdict = compute_dor_score(req_result, plan_result)
            else:
                # Gap filler exhausted — no structural improvements possible, needs human decision
                verdict = "needs_decision"

        assessed_at = datetime.now(UTC).isoformat()

        # Write DOR report
        report_path = todo_dir / "dor-report.md"
        _write_dor_report(
            report_path,
            slug,
            score,
            verdict,
            req_result,
            plan_result,
            all_edits,
            assessed_at,
            current_commit,
        )

        # Update state.yaml dor section
        all_gaps = req_result["gaps"] + plan_result["gaps"]
        state["dor"] = cast(
            StateValue,
            {
                "last_assessed_at": assessed_at,
                "score": score,
                "status": verdict,
                "schema_version": 1,
                "blockers": all_gaps[:10],
                "actions_taken": {
                    "requirements_updated": any("requirements" in e for e in all_edits),
                    "implementation_plan_updated": any("plan" in e.lower() for e in all_edits),
                },
                "assessed_commit": current_commit,
            },
        )
        _write_state_yaml(state_path, state)

        logger.info(
            "prepare-quality: assessment complete",
            slug=slug,
            score=score,
            verdict=verdict,
            edits=len(all_edits),
        )

        # Notification lifecycle
        if notification_id is not None:
            if verdict in ("pass", "needs_work"):
                await context.db.resolve_notification(
                    notification_id,
                    cast(
                        JsonDict,
                        {"verdict": verdict, "score": score, "assessed_by": "prepare-quality-runner"},
                    ),
                )
            else:
                # needs_decision — leave unresolved, log blockers
                logger.info(
                    "prepare-quality: needs_decision — leaving notification unresolved",
                    slug=slug,
                    blockers=all_gaps[:5],
                )

        # Emit dor_assessed event
        try:
            await emit_event(
                event="domain.software-development.planning.dor_assessed",
                source="prepare-quality-runner",
                level=EventLevel.WORKFLOW,
                domain="software-development",
                visibility=EventVisibility.LOCAL,
                entity=slug,
                description=f"DOR assessed for {slug}: {verdict} (score {score}/10)",
                payload=cast(
                    JsonDict,
                    {"slug": slug, "score": score, "verdict": verdict, "assessed_commit": current_commit},
                ),
            )
        except RuntimeError:
            # Producer not configured (e.g., in tests) — acceptable
            logger.debug("prepare-quality: producer not configured, skipping dor_assessed emit", slug=slug)


def _is_slug_delivered_or_frozen(slug: str, project_root: Path) -> bool:
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
