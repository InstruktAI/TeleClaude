"""Unified validation for doc snippets and agent artifacts.

This module is the single source of truth for validating all markdown resources:
- Doc snippets (frontmatter, structure, sections, inline refs)
- Agent artifacts (commands, agents, skills — schema, frontmatter, refs)
- Baseline index refs
- Third-party doc sources

Called by ``telec sync`` and pre-commit hooks. Read-only — never modifies files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import frontmatter
import yaml
from pydantic import ValidationError

from teleclaude.config.schema import JobWhenConfig
from teleclaude.resource_validation._models import (
    _ARTIFACT_REF_ORDER,
    REPO_ROOT,
    _as_str_list,
    _error,
    _load_schema,
    _warn,
    clear_warnings,
    get_errors,
    get_warnings,
)
from teleclaude.resource_validation._snippet import (
    _extract_markdown_link_url,
    _extract_sources_section,
    _infer_type_from_path,
    _is_context7_id,
    _is_global_doc,
    _is_web_url,
    _iter_snippet_roots,
    _normalize_section_title,
    _resolve_see_also_ref,
    _resolve_snippet_ref,
    _validate_baseline_index,
    _validate_see_also_ref,
    _validate_snippet_refs,
    _validate_snippet_sections,
    _validate_snippet_structure,
    collect_inline_ref_errors,
    iter_inline_refs,
    resolve_ref_path,
    validate_all_snippets,
    validate_snippet,
    validate_third_party_docs,
)
from teleclaude.types.todos import TodoState

__all__ = [
    # Public API
    "REPO_ROOT",
    # Re-exported internals
    "_ARTIFACT_REF_ORDER",
    "_as_str_list",
    "_error",
    "_extract_markdown_link_url",
    "_extract_sources_section",
    "_infer_type_from_path",
    "_is_context7_id",
    "_is_global_doc",
    "_is_web_url",
    "_iter_snippet_roots",
    "_load_schema",
    "_normalize_section_title",
    "_resolve_see_also_ref",
    "_resolve_snippet_ref",
    "_validate_baseline_index",
    "_validate_see_also_ref",
    "_validate_snippet_refs",
    "_validate_snippet_sections",
    "_validate_snippet_structure",
    "_warn",
    "clear_warnings",
    "collect_inline_ref_errors",
    "get_errors",
    "get_warnings",
    "iter_inline_refs",
    "resolve_ref_path",
    "validate_all_artifacts",
    "validate_all_snippets",
    "validate_all_todos",
    "validate_artifact",
    "validate_artifact_body",
    "validate_artifact_frontmatter",
    "validate_artifact_refs_exist",
    "validate_jobs_config",
    "validate_snippet",
    "validate_third_party_docs",
    "validate_todo",
]


# ---------------------------------------------------------------------------
# Agent artifact validation
# ---------------------------------------------------------------------------


def _taxonomy_from_ref(ref: str) -> str | None:
    for taxonomy in _ARTIFACT_REF_ORDER:
        if f"/{taxonomy}/" in ref:
            return taxonomy
    return None


def _extract_artifact_required_reads(lines: list[str]) -> list[str]:
    """Extract ``@`` refs from a Required reads section after the H1 title."""
    refs: list[str] = []
    in_required_reads = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            if stripped.startswith("## ") or stripped.startswith("# "):
                break
            if stripped.startswith("@"):
                refs.append(stripped[1:].strip())
                continue
            if stripped.startswith("- @"):
                refs.append(stripped[3:].strip())
                continue
            if not stripped:
                continue
            break
    return refs


def _next_nonblank(lines: list[str], idx: int) -> tuple[str | None, int]:
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return None, idx
    return lines[idx], idx


def validate_artifact_frontmatter(post: frontmatter.Post, path: str, *, kind: str) -> None:
    """Validate frontmatter fields for an agent artifact."""
    description = post.metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{kind.title()} {path} is missing frontmatter 'description'")
    if kind == "skill":
        name = post.metadata.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Skill {path} is missing frontmatter 'name'")
    parameters = post.metadata.get("parameters")
    if parameters is not None:
        _validate_parameters_field(parameters, path)


def _validate_parameters_field(parameters: object, path: str) -> None:
    """Validate the ``parameters`` frontmatter field shape.

    Position is implicit from list order — no explicit ``position`` field.
    """
    if not isinstance(parameters, list):
        raise ValueError(f"{path} frontmatter 'parameters' must be a list")
    seen_names: set[str] = set()
    for param in parameters:
        if not isinstance(param, dict):
            raise ValueError(f"{path} each parameter must be a mapping")
        name = param.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path} each parameter must have a 'name' string")
        if name in seen_names:
            raise ValueError(f"{path} duplicate parameter name '{name}'")
        seen_names.add(name)


def _validate_artifact_argument_hint(post: frontmatter.Post, path: str, *, kind: str) -> None:
    argument_hint = post.metadata.get("argument-hint")
    if kind == "command" and argument_hint is not None and not isinstance(argument_hint, str):
        raise ValueError(f"{path} has invalid frontmatter 'argument-hint' (must be a string)")


def _find_required_reads_block(lines: list[str], h1_idx: int) -> tuple[int | None, int | None]:
    required_reads_idx = None
    required_reads_end = None
    for i in range(h1_idx + 1, len(lines)):
        if lines[i].strip().lower() != "## required reads":
            continue
        required_reads_idx = i
        j = i + 1
        while j < len(lines):
            stripped = lines[j].strip()
            if not stripped:
                j += 1
                continue
            if stripped.startswith("@") or stripped.startswith("- @"):
                j += 1
                continue
            if stripped.startswith("# "):
                break
            if stripped.startswith("## ") and stripped.lower() != "## required reads":
                break
            break
        required_reads_end = j
        break
    return required_reads_idx, required_reads_end


def _validate_required_reads_block_position(
    lines: list[str],
    path: str,
    *,
    h1_idx: int,
    required_reads_idx: int | None,
    required_reads_end: int | None,
) -> None:
    if required_reads_idx is None:
        return
    for i in range(h1_idx + 1, required_reads_idx):
        if lines[i].strip().startswith("## "):
            raise ValueError(f"{path} must place Required reads before other H2 sections")
    for i in range(required_reads_idx + 1, required_reads_end or len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith("@") or stripped.startswith("- @"):
            continue
        break


def _find_first_artifact_section(lines: list[str], h1_idx: int) -> int | None:
    for i in range(h1_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## ") and stripped.lower() != "## required reads":
            return i
    return None


def _validate_artifact_role_activation(
    lines: list[str],
    path: str,
    *,
    kind: str,
    h1_idx: int,
    first_section_idx: int,
) -> None:
    role_lines = [line.strip() for line in lines]
    if kind in {"command", "agent"}:
        has_role = any(line.startswith("You are now the ") for line in role_lines[h1_idx + 1 : first_section_idx])
        if not has_role:
            raise ValueError(f"{path} must include a role activation line before the first section")
        return
    if any(line.startswith("You are now the ") for line in role_lines):
        raise ValueError(f"{path} must not include a role activation line")


def _artifact_section_order(kind: str) -> list[str]:
    if kind == "command":
        return ["Purpose", "Inputs", "Outputs", "Steps", "Discipline"]
    return ["Purpose", "Scope", "Inputs", "Outputs", "Procedure"]


def _collect_artifact_headings(lines: list[str], path: str, *, h1_idx: int) -> list[str]:
    headings: list[str] = []
    in_required_reads = False
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            if stripped.startswith("## ") or stripped.startswith("# "):
                in_required_reads = False
            else:
                continue
        if stripped.startswith("@") or stripped.startswith("- @"):
            raise ValueError(f"{path} has inline refs outside the required reads block")
        if stripped.startswith("# "):
            if idx != h1_idx:
                raise ValueError(f"{path} must only have one H1 title")
            continue
        if stripped.startswith("### "):
            raise ValueError(f"{path} must use H2 headings only for schema sections")
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if title.lower() != "required reads":
                headings.append(title)
    return headings


def _validate_artifact_section_order(lines: list[str], path: str, *, kind: str, h1_idx: int) -> None:
    headings = _collect_artifact_headings(lines, path, h1_idx=h1_idx)
    if not headings:
        raise ValueError(f"{path} is missing required section headings")
    required = _artifact_section_order(kind)
    for heading in headings:
        if heading not in required:
            raise ValueError(f"{path} has invalid section heading '{heading}'")
    if headings != required:
        raise ValueError(f"{path} section order must be: {' → '.join(required)}")


def validate_artifact_body(post: frontmatter.Post, path: str, *, kind: str) -> None:
    """Validate body structure of an agent artifact (command, agent, or skill)."""
    _validate_artifact_argument_hint(post, path, kind=kind)
    lines = post.content.splitlines()
    first_line, h1_idx = _next_nonblank(lines, 0)
    if first_line is None or not first_line.startswith("# "):
        raise ValueError(f"{path} must start with an H1 title")

    required_reads_idx, required_reads_end = _find_required_reads_block(lines, h1_idx)
    _validate_required_reads_block_position(
        lines,
        path,
        h1_idx=h1_idx,
        required_reads_idx=required_reads_idx,
        required_reads_end=required_reads_end,
    )

    refs = _extract_artifact_required_reads(lines)
    _validate_required_reads_order(refs, path)

    first_section_idx = _find_first_artifact_section(lines, h1_idx)
    if first_section_idx is None:
        raise ValueError(f"{path} is missing required section headings")
    _validate_artifact_role_activation(lines, path, kind=kind, h1_idx=h1_idx, first_section_idx=first_section_idx)
    _validate_artifact_section_order(lines, path, kind=kind, h1_idx=h1_idx)


def _validate_required_reads_order(refs: list[str], path: str) -> None:
    last_index = -1
    for ref in refs:
        taxonomy = _taxonomy_from_ref(ref)
        if not taxonomy:
            continue
        index = _ARTIFACT_REF_ORDER.index(taxonomy)
        if index < last_index:
            raise ValueError(f"{path} required reads are out of order; expected {' → '.join(_ARTIFACT_REF_ORDER)}")
        last_index = index


def validate_artifact_refs_exist(refs: list[str], path: str, *, project_root: Path) -> None:
    """Raise if any artifact ``@`` ref points to a non-existent file."""
    current_path = Path(path)
    for ref in refs:
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
        if not resolved or not resolved.exists():
            raise ValueError(f"{path} references non-existent file: {ref}")


def validate_artifact(post: frontmatter.Post, path: str, *, kind: str, project_root: Path) -> None:
    """Full validation of an agent artifact."""
    validate_artifact_frontmatter(post, path, kind=kind)
    validate_artifact_body(post, path, kind=kind)
    refs = _extract_artifact_required_reads(post.content.splitlines())
    if refs:
        validate_artifact_refs_exist(refs, path, project_root=project_root)
    if kind == "skill":
        name = post.metadata.get("name")
        dirname = Path(path).parent.name
        if isinstance(name, str) and name != dirname:
            raise ValueError(f"Skill name '{name}' must match folder '{dirname}'")


# ---------------------------------------------------------------------------
# Top-level validation entry points
# ---------------------------------------------------------------------------


def validate_all_artifacts(project_root: Path) -> list[str]:
    """Validate all agent artifact source files. Returns list of errors."""
    teleclaude_root = REPO_ROOT
    is_mother_project = Path(project_root).resolve() == teleclaude_root.resolve()
    agents_root = teleclaude_root / "agents"
    dot_agents_root = project_root / ".agents"

    global_sources: list[dict[str, str]] = []
    if is_mother_project:
        global_sources = [
            {
                "label": "agents",
                "agents_dir": str(agents_root / "agents"),
                "commands": str(agents_root / "commands"),
                "skills": str(agents_root / "skills"),
            }
        ]
    local_sources = [
        {
            "label": ".agents",
            "agents_dir": str(dot_agents_root / "agents"),
            "commands": str(dot_agents_root / "commands"),
            "skills": str(dot_agents_root / "skills"),
        },
    ]

    kind_map = {"agents_dir": "agent", "commands": "command", "skills": "skill"}
    errors: list[str] = []

    for sources in (global_sources, local_sources):
        for source in sources:
            for dir_key, kind in kind_map.items():
                source_dir = source.get(dir_key)
                if not source_dir or not os.path.isdir(source_dir):
                    continue
                if kind == "skill":
                    items = [f for f in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, f))]
                else:
                    items = [f for f in os.listdir(source_dir) if f.endswith(".md")]
                for item in sorted(items):
                    if kind == "skill":
                        item_path = os.path.join(source_dir, item, "SKILL.md")
                    else:
                        item_path = os.path.join(source_dir, item)
                    if not os.path.exists(item_path):
                        continue
                    try:
                        with open(item_path) as f:
                            post = frontmatter.load(f)
                        validate_artifact(post, item_path, kind=kind, project_root=project_root)
                    except Exception as e:
                        errors.append(str(e))
    return errors


def _job_slug_to_spec_filename(job_slug: str) -> str:
    return f"{job_slug.replace('_', '-')}.md"


def _validate_job_when_or_schedule(
    job_cfg: dict[object, object],
    *,
    name: object,
    config_path: Path,
    allowed_schedules: set[str],
) -> list[str]:
    errors: list[str] = []
    when_raw = job_cfg.get("when")
    has_valid_when = False
    if when_raw is not None:
        if not isinstance(when_raw, dict):
            errors.append(f"{config_path}: jobs.{name}.when must be a mapping")
        else:
            try:
                JobWhenConfig.model_validate(when_raw)
                has_valid_when = True
            except ValidationError as exc:
                first = exc.errors()[0] if exc.errors() else {"msg": "invalid when config"}
                errors.append(f"{config_path}: jobs.{name}.when {first['msg']}")
    if has_valid_when:
        return errors
    schedule = job_cfg.get("schedule")
    if not isinstance(schedule, str) or schedule not in allowed_schedules:
        errors.append(f"{config_path}: jobs.{name}.schedule must be one of {sorted(allowed_schedules)}")
    return errors


def _validate_job_preferences(job_cfg: dict[object, object], *, name: object, config_path: Path) -> list[str]:
    errors: list[str] = []
    preferred_hour = job_cfg.get("preferred_hour", 6)
    if not isinstance(preferred_hour, int) or not (0 <= preferred_hour <= 23):
        errors.append(f"{config_path}: jobs.{name}.preferred_hour must be int 0..23")

    preferred_weekday = job_cfg.get("preferred_weekday", 0)
    if not isinstance(preferred_weekday, int) or not (0 <= preferred_weekday <= 6):
        errors.append(f"{config_path}: jobs.{name}.preferred_weekday must be int 0..6")

    preferred_day = job_cfg.get("preferred_day", 1)
    if not isinstance(preferred_day, int) or not (1 <= preferred_day <= 31):
        errors.append(f"{config_path}: jobs.{name}.preferred_day must be int 1..31")
    return errors


def _validate_job_execution_target(
    job_cfg: dict[object, object],
    *,
    name: object,
    config_path: Path,
    project_root: Path,
) -> list[str]:
    errors: list[str] = []
    is_agent = str(job_cfg.get("type", "")) == "agent"
    if is_agent:
        if "message" in job_cfg:
            errors.append(f"{config_path}: jobs.{name}.message is not allowed for agent jobs")
        job_ref = job_cfg.get("job")
        if not isinstance(job_ref, str) or not job_ref.strip():
            errors.append(f"{config_path}: jobs.{name}.job is required for agent jobs")
            return errors
        spec_file = project_root / "docs" / "project" / "spec" / "jobs" / _job_slug_to_spec_filename(job_ref)
        if not spec_file.exists():
            errors.append(f"{config_path}: jobs.{name}.job references missing spec {spec_file}")
        return errors

    script_ref = job_cfg.get("script")
    if isinstance(script_ref, str) and script_ref.strip():
        return errors
    python_module_path = project_root / "jobs" / f"{name}.py"
    if not python_module_path.exists():
        errors.append(f"{config_path}: jobs.{name} has no script and missing python module {python_module_path}")
    return errors


def _validate_single_job_config(
    name: object,
    raw: object,
    *,
    config_path: Path,
    project_root: Path,
    allowed_schedules: set[str],
) -> list[str]:
    if not isinstance(raw, dict):
        return [f"{config_path}: jobs.{name} must be a mapping"]
    return [
        *_validate_job_when_or_schedule(raw, name=name, config_path=config_path, allowed_schedules=allowed_schedules),
        *_validate_job_preferences(raw, name=name, config_path=config_path),
        *_validate_job_execution_target(raw, name=name, config_path=config_path, project_root=project_root),
    ]


def validate_jobs_config(project_root: Path) -> list[str]:
    """Validate project job config in teleclaude.yml.

    Checks schedule shape, execution mode contract, and job/spec/module references.
    """
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return []

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return [f"{config_path}: invalid YAML ({exc})"]

    if not isinstance(config, dict):
        return [f"{config_path}: expected top-level mapping"]

    jobs = config.get("jobs", {})
    if not isinstance(jobs, dict):
        return [f"{config_path}: jobs must be a mapping"]

    allowed_schedules = {"hourly", "daily", "weekly", "monthly"}
    errors: list[str] = []

    for name, raw in jobs.items():
        errors.extend(
            _validate_single_job_config(
                name,
                raw,
                config_path=config_path,
                project_root=project_root,
                allowed_schedules=allowed_schedules,
            )
        )

    return errors


def validate_todo(slug: str, project_root: Path) -> list[str]:
    """Validate a todo directory structure and state.yaml schema (with state.json fallback)."""
    todos_root = project_root / "todos"
    todo_dir = todos_root / slug
    if not todo_dir.is_dir():
        return [f"Todo directory missing: {todo_dir}"]

    errors = []

    # 1. state.yaml schema validation (with state.json fallback)
    state_path = todo_dir / "state.yaml"
    # Backward compat: fall back to state.json
    if not state_path.exists():
        legacy_path = todo_dir / "state.json"
        if legacy_path.exists():
            state_path = legacy_path

    if not state_path.exists():
        errors.append(f"{slug}: missing state.yaml")
    else:
        try:
            content = state_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            TodoState.model_validate(data)
        except Exception as exc:
            errors.append(f"{slug}: state file schema violation: {exc}")

    # 2. Required files for Ready state
    # If build is pending and score >= 8, requirements and implementation plan MUST exist
    if state_path.exists():
        try:
            state = TodoState.model_validate(yaml.safe_load(state_path.read_text(encoding="utf-8")))
            if state.build == "pending" and state.dor and state.dor.score >= 8:
                if not (todo_dir / "requirements.md").exists():
                    errors.append(f"{slug}: marked as Ready (score {state.dor.score}) but missing requirements.md")
                if not (todo_dir / "implementation-plan.md").exists():
                    errors.append(
                        f"{slug}: marked as Ready (score {state.dor.score}) but missing implementation-plan.md"
                    )
        except Exception:
            pass  # already reported in schema check

    return errors


def validate_all_todos(project_root: Path) -> list[str]:
    """Enumerate and validate all active todos."""
    todos_root = project_root / "todos"
    if not todos_root.is_dir():
        return []

    # Exclude delivered and icebox
    delivered = set()
    delivered_path = todos_root / "delivered.md"
    if delivered_path.exists():
        # simple regex to extract slugs from markdown table
        delivered = set(re.findall(r"\|\s*([a-z0-9-]+)\s*\|", delivered_path.read_text(encoding="utf-8")))

    icebox = set()
    icebox_path = todos_root / "icebox.md"
    if icebox_path.exists():
        icebox = set(re.findall(r"\|\s*([a-z0-9-]+)\s*\|", icebox_path.read_text(encoding="utf-8")))

    errors = []
    if not todos_root.exists():
        return []

    for entry in todos_root.iterdir():
        if entry.is_dir() and entry.name not in delivered and entry.name not in icebox:
            # Skip hidden dirs, __pycache__, and the _icebox subfolder
            if entry.name.startswith(".") or entry.name == "__pycache__" or entry.name == "_icebox":
                continue
            errors.extend(validate_todo(entry.name, project_root))

    return errors
