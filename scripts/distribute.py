#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, NotRequired, TypedDict, cast

import frontmatter
import yaml
from frontmatter import Post
from frontmatter.default_handlers import YAMLHandler

SubstitutionMap = dict[str, str]
Transform = Callable[[Post], str]

INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")


class StableYAMLHandler(YAMLHandler):
    """Frontmatter YAML handler with stable ordering and wide line width."""

    def export(self, metadata: dict[str, object], **kwargs: object) -> str:  # guard: loose-dict - frontmatter contract
        return yaml.safe_dump(
            metadata,
            sort_keys=False,
            width=1000,
            default_flow_style=False,
            allow_unicode=True,
        ).rstrip()


_FRONTMATTER_HANDLER = StableYAMLHandler()


def dump_frontmatter(post: Post) -> str:
    """Serialize frontmatter using the stable YAML handler."""
    return frontmatter.dumps(post, handler=_FRONTMATTER_HANDLER)


def _format_markdown(paths: list[str]) -> None:
    """Format markdown outputs using the repo prettier setup."""
    md_files = [p for p in paths if p.endswith(".md") and os.path.exists(p)]
    if not md_files:
        return
    prettier = shutil.which("prettier")
    if prettier:
        subprocess.run([prettier, "--write", *md_files], check=False)
        return
    subprocess.run(["npx", "--yes", "prettier", "--write", *md_files], check=False)


ArtifactFrontmatter = TypedDict(
    "ArtifactFrontmatter",
    {
        "description": str,
        "name": str,
        "argument-hint": str,
        "hooks": object,
    },
    total=False,
)


class AgentConfig(TypedDict):
    check_dir: str
    prefix: str
    master_dest: str
    commands_dest_dir: str
    agents_dest_dir: str
    skills_dest_dir: str
    skills_ext: str
    ext: str
    transform: Transform
    deploy_master_dest: NotRequired[str]
    deploy_commands_dest: NotRequired[str]
    deploy_agents_dest: NotRequired[str]
    deploy_skills_dest: NotRequired[str]


@dataclass(frozen=True)
class FileArtifactType:
    name: str
    source_dir_key: str
    dest_dir_key: str
    deploy_dir_key: str
    ext_key: str
    kind: Literal["file", "skill"]
    validator: Callable[[Post, str], None]


def transform_to_codex(post: Post) -> str:
    """Transform a post to the Codex format (same as Claude - standard YAML frontmatter)."""
    # Codex uses the same format as Claude: standard Markdown with YAML frontmatter
    return dump_frontmatter(post)


def transform_to_gemini(post: Post) -> str:
    """Transform a post to the Gemini TOML format."""
    description = post.metadata.get("description", "")

    description_str = f'"""{description}"""'

    # replace $ARGUMENTS for {{args}} in gemini format
    content = post.content.replace("$ARGUMENTS", "{{args}}")

    return f"description = {description_str}\nprompt = '''\n{content}\n'''\n"


def transform_skill_to_claude(post: Post, name: str) -> str:
    """Transform a skill post to Claude format."""
    description = post.metadata.get("description", "")
    transformed_post = Post(post.content, name=name, description=description)
    return dump_frontmatter(transformed_post)


def transform_skill_to_codex(post: Post, name: str) -> str:
    """Transform a skill post to Codex markdown format."""
    metadata = dict(post.metadata)
    metadata["name"] = name
    metadata["description"] = metadata.get("description", "")
    transformed_post = Post(post.content, **metadata)
    return dump_frontmatter(transformed_post)


def transform_skill_to_gemini(post: Post, name: str) -> str:
    """Transform a skill post to Gemini TOML format."""
    description = post.metadata.get("description", "")
    description_str = f'"""{description}"""'
    content = post.content
    return f"name = \"{name}\"\ndescription = {description_str}\nprompt = '''\n{content}\n'''\n"


def _validate_agent_frontmatter(post: Post, path: str) -> None:
    """Validate frontmatter for agent artifacts."""
    description = post.metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Agent artifact {path} is missing frontmatter 'description'")


def _validate_command_frontmatter(post: Post, path: str) -> None:
    """Validate frontmatter for command artifacts."""
    description = post.metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Command {path} is missing frontmatter 'description'")


def _validate_skill_frontmatter(post: Post, path: str) -> None:
    """Validate frontmatter for skill artifacts."""
    description = post.metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Skill {path} is missing frontmatter 'description'")


_ARTIFACT_REF_ORDER = ["concept", "principle", "policy", "role", "procedure", "reference"]


def _taxonomy_from_ref(ref: str) -> str | None:
    for taxonomy in _ARTIFACT_REF_ORDER:
        if f"/{taxonomy}/" in ref:
            return taxonomy
    return None


def _extract_required_reads(lines: list[str]) -> tuple[list[str], int]:
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    refs: list[str] = []
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped:
            idx += 1
            continue
        if stripped.startswith("@"):
            refs.append(stripped[1:].strip())
            idx += 1
            continue
        break
    return refs, idx


def _next_nonblank(lines: list[str], idx: int) -> tuple[str | None, int]:
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return None, idx
    return lines[idx], idx


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


def _validate_body_schema(post: Post, path: str, *, kind: str) -> None:
    argument_hint = post.metadata.get("argument-hint")
    if kind == "command" and argument_hint is not None and not isinstance(argument_hint, str):
        raise ValueError(f"{path} has invalid frontmatter 'argument-hint' (must be a string)")
    lines = post.content.splitlines()
    refs, idx = _extract_required_reads(lines)
    _validate_required_reads_order(refs, path)

    line, idx = _next_nonblank(lines, idx)
    if line is None or not line.startswith("# "):
        raise ValueError(f"{path} must start with an H1 title after required reads")
    idx += 1

    line, idx = _next_nonblank(lines, idx)
    if kind in {"command", "agent"}:
        if line is None or not line.strip().startswith("You are now the "):
            raise ValueError(f"{path} must include role activation line after the title")
        idx += 1
    else:
        if line is not None and line.strip().startswith("You are now the "):
            raise ValueError(f"{path} must not include a role activation line")

    line, idx = _next_nonblank(lines, idx)
    if line is None:
        raise ValueError(f"{path} is missing required section headings")

    allowed_map = {
        "command": ["Purpose", "Inputs", "Outputs", "Steps", "Examples"],
        "skill": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure", "Examples"],
        "agent": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure", "Examples"],
    }
    required_map = {
        "command": ["Purpose", "Inputs", "Outputs", "Steps"],
        "skill": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure"],
        "agent": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure"],
    }
    allowed = allowed_map[kind]
    required = required_map[kind]

    headings: list[str] = []
    for raw in lines[idx:]:
        stripped = raw.strip()
        if stripped.startswith("@"):
            raise ValueError(f"{path} has inline refs outside the required reads block")
        if stripped.startswith("# "):
            raise ValueError(f"{path} must only have one H1 title")
        if stripped.startswith("### "):
            raise ValueError(f"{path} must use H2 headings only for schema sections")
        if stripped.startswith("## "):
            headings.append(stripped[3:].strip())

    if not headings:
        raise ValueError(f"{path} is missing required section headings")

    for heading in headings:
        if heading not in allowed:
            raise ValueError(f"{path} has invalid section heading '{heading}'")

    if headings != required and headings != required + ["Examples"]:
        raise ValueError(f"{path} section order must be: {' → '.join(required)} (optional Examples at end)")


def _validate_command(post: Post, path: str) -> None:
    _validate_command_frontmatter(post, path)
    _validate_body_schema(post, path, kind="command")


def _validate_agent(post: Post, path: str) -> None:
    _validate_agent_frontmatter(post, path)
    _validate_body_schema(post, path, kind="agent")


def _validate_skill(post: Post, path: str) -> None:
    _validate_skill_frontmatter(post, path)
    _validate_body_schema(post, path, kind="skill")


def _should_expand_inline(agent_name: str) -> bool:
    return agent_name in {"claude", "codex", "gemini"}


def _filter_frontmatter(metadata: ArtifactFrontmatter, agent_name: str) -> ArtifactFrontmatter:
    filtered = cast(ArtifactFrontmatter, dict(metadata))
    if agent_name != "claude":
        filtered.pop("hooks", None)
    return filtered


def _prepare_post(
    post: Post,
    *,
    agent_prefix: str,
    agent_name: str,
    project_root: Path,
    current_path: Path,
) -> Post:
    content = process_file(post.content, agent_prefix, agent_name)
    if _should_expand_inline(agent_name):
        content = expand_inline_refs(content, project_root=project_root, current_path=current_path)
    metadata = _filter_frontmatter(post.metadata, agent_name)
    return Post(content, **metadata)


def resolve_skill_name(post: Post, dirname: str) -> str:
    """Resolve the skill name from metadata and validate its directory."""
    name = cast(str, post.metadata.get("name"))
    if not name:
        raise ValueError(f"Skill {dirname} is missing frontmatter 'name'")
    if name != dirname:
        raise ValueError(f"Skill name '{name}' must match folder '{dirname}'")
    return name


def process_file(content: str, agent_prefix: str, agent_name: str) -> str:
    """Apply substitutions to the file content."""
    content = content.replace("{AGENT_PREFIX}", agent_prefix)
    content = content.replace("{{agent}}", agent_name)
    return content


def _resolve_ref_path(ref: str, *, root_path: Path, current_path: Path) -> Path | None:
    if "://" in ref:
        return None
    candidate = Path(ref).expanduser()
    if not candidate.is_absolute():
        if str(candidate).startswith("docs/"):
            candidate = (root_path / candidate).resolve()
            if not candidate.exists():
                tail = Path(ref).relative_to("docs")
                project_candidate = (root_path / "docs" / "project" / tail).resolve()
                if project_candidate.exists():
                    candidate = project_candidate
                else:
                    global_candidate = (root_path / "docs" / "global" / tail).resolve()
                    if global_candidate.exists():
                        candidate = global_candidate
        else:
            candidate = (current_path.parent / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def expand_inline_refs(content: str, *, project_root: Path, current_path: Path) -> str:
    """Inline @path.md references into the content (Codex speedup)."""
    seen: set[Path] = set()
    content = _strip_required_reads(content)

    def _expand(text: str, *, current_path: Path, depth: int) -> str:
        if depth <= 0:
            return text

        def _replace(match: re.Match[str]) -> str:
            ref = match.group(1)
            resolved = _resolve_ref_path(ref, root_path=project_root, current_path=current_path)
            if not resolved or not resolved.exists():
                return match.group(0)
            if resolved in seen:
                return ""
            seen.add(resolved)
            raw = resolved.read_text(encoding="utf-8")
            post = frontmatter.loads(raw)
            body = post.content
            if resolved.name == "index.md":
                expanded = _expand(body, current_path=resolved, depth=depth - 1).strip()
                expanded = _strip_required_reads(expanded).strip()
                return f"{expanded}\n" if expanded else ""
            expanded = _expand(body, current_path=resolved, depth=depth - 1).strip()
            expanded = _strip_required_reads(expanded)
            expanded = _strip_specific_h1(expanded, "Project baseline").strip()
            if not expanded:
                return ""
            return f"---\n\n{expanded}\n"

        return INLINE_REF_RE.sub(_replace, text)

    return _expand(content, current_path=current_path, depth=20)


def _strip_required_reads(content: str) -> str:
    """Remove Required Reads section after inlining references."""
    lines = content.splitlines()
    output: list[str] = []
    in_required_reads = False

    for line in lines:
        if line.strip().lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            if line.startswith("## "):
                in_required_reads = False
                output.append(line)
            continue
        output.append(line)

    return "\n".join(output).rstrip() + "\n"


def _strip_specific_h1(content: str, title: str) -> str:
    """Remove a specific leading H1 heading to avoid redundant titles in inlined docs."""
    lines = content.splitlines()
    if not lines:
        return content
    if lines[0].strip() == f"# {title}":
        return "\n".join(lines[1:]).lstrip("\n")
    return content


def _iter_project_agent_masters(project_root: Path) -> list[Path]:
    """Find AGENTS.master.md files in the project (excluding tool-managed dirs)."""
    skip_dirs = {
        ".git",
        ".agents",
        "__pycache__",
        "dist",
        "node_modules",
        ".venv",
        "venv",
    }
    matches: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        if "AGENTS.master.md" in files:
            matches.append(Path(root) / "AGENTS.master.md")
    return sorted(matches)


def _write_project_agents(master_path: Path, *, project_root: Path) -> None:
    """Generate AGENTS.md and CLAUDE.md next to a project AGENTS.master.md."""
    raw = master_path.read_text(encoding="utf-8")
    inflated = expand_inline_refs(raw, project_root=project_root, current_path=master_path)
    agents_path = master_path.parent / "AGENTS.md"
    agents_path.write_text(inflated, encoding="utf-8")
    claude_path = master_path.parent / "CLAUDE.md"
    claude_path.write_text("@./AGENTS.md\n", encoding="utf-8")


def _merge_global_index(deploy_docs_root: str) -> None:
    """Merge index.yaml files from multiple projects into single global index.

    When multiple projects publish to ~/.teleclaude/docs/, each brings its own
    index.yaml with snippets. This merges them, preserving source_project metadata.
    """
    import yaml

    # Note: After copytree with dirs_exist_ok=True, only the most recent
    # project's index.yaml remains. To truly merge, we'd need to track indexes
    # before copy. For now, just ensure the final index is correct.

    # The current index.yaml should already have source_project from sync_resources.py
    # Just rewrite paths to match deployed location
    index_path = os.path.join(deploy_docs_root, "index.yaml")
    if not os.path.exists(index_path):
        return

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, dict):
            # Use tilde for portability (git filters will expand in working copy)
            data["project_root"] = "~/.teleclaude"
            data["snippets_root"] = "~/.teleclaude/docs"
            snippets = data.get("snippets")
            if isinstance(snippets, list):
                for entry in snippets:
                    if not isinstance(entry, dict):
                        continue
                    path = entry.get("path")
                    if not isinstance(path, str):
                        continue
                    if path.startswith("docs/global/"):
                        entry["path"] = path.replace("docs/global/", "docs/", 1)

            with open(index_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, sort_keys=False, allow_unicode=True)
    except Exception as e:
        print(f"Warning: Could not process global index: {e}")


def rewrite_global_index(index_path: str, deploy_root: str) -> None:
    """Rewrite global docs index to match deployed paths."""
    index_file = Path(index_path)
    if not index_file.exists():
        return
    lines = index_file.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    for line in lines:
        if line.startswith("project_root:"):
            new_lines.append(f"project_root: {deploy_root}")
            continue
        if line.startswith("snippets_root:"):
            new_lines.append(f"snippets_root: {os.path.join(deploy_root, 'docs')}")
            continue
        if "path: agents/docs/" in line:
            new_lines.append(line.replace("path: agents/docs/", "path: docs/"))
            continue
        if "path: docs/global/" in line:
            new_lines.append(line.replace("path: docs/global/", "path: docs/"))
            continue
        new_lines.append(line)
    index_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transpile and distribute agent markdown files.")
    parser.add_argument("--deploy", action="store_true", help="Sync generated files to their locations.")
    parser.add_argument(
        "--project-root",
        required=True,
        help="Project root to read agents/.agents from (default: script parent).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate artifact schema without generating outputs.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Emit validation warnings but exit successfully.",
    )
    args = parser.parse_args()

    # Get the project root and main TeleClaude repo root.
    script_dir = os.path.dirname(os.path.realpath(__file__))
    teleclaude_root = os.path.dirname(script_dir)
    project_root = os.path.abspath(os.path.expanduser(args.project_root))
    is_mother_project = Path(project_root).resolve() == Path(teleclaude_root).resolve()
    project_root_path = Path(project_root)
    agents_root = os.path.join(teleclaude_root, "agents")
    dot_agents_root = os.path.join(project_root, ".agents")
    os.chdir(project_root)

    for master_path in _iter_project_agent_masters(project_root_path):
        _write_project_agents(master_path, project_root=project_root_path)

    validate_only = args.validate_only or args.warn_only
    dist_dir = "dist"

    master_agents_file = os.path.join(agents_root, "AGENTS.global.md")
    master_agents_dir = os.path.join(agents_root, "agents")
    master_commands_dir = os.path.join(agents_root, "commands")
    master_skills_dir = os.path.join(agents_root, "skills")

    dot_master_agents_dir = os.path.join(dot_agents_root, "agents")
    dot_master_commands_dir = os.path.join(dot_agents_root, "commands")
    dot_master_skills_dir = os.path.join(dot_agents_root, "skills")
    master_docs_dir = os.path.join(project_root, "docs", "global")

    agents_config: dict[str, AgentConfig] = {
        "claude": {
            "check_dir": os.path.expanduser("~/.claude"),
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "claude", "CLAUDE.md"),
            "commands_dest_dir": os.path.join(dist_dir, "claude", "commands"),
            "agents_dest_dir": os.path.join(dist_dir, "claude", "agents"),
            "skills_dest_dir": os.path.join(dist_dir, "claude", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.claude"), "CLAUDE.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.claude"), "commands"),
            "deploy_agents_dest": os.path.join(os.path.expanduser("~/.claude"), "agents"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.claude"), "skills"),
            "ext": ".md",
            "transform": dump_frontmatter,
        },
        "codex": {
            "check_dir": os.path.expanduser("~/.codex"),
            "prefix": "~/.codex/prompts/",
            "master_dest": os.path.join(dist_dir, "codex", "CODEX.md"),
            "commands_dest_dir": os.path.join(dist_dir, "codex", "prompts"),
            "agents_dest_dir": os.path.join(dist_dir, "codex", "agents"),
            "skills_dest_dir": os.path.join(dist_dir, "codex", "skills"),
            "skills_ext": ".md",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.codex"), "CODEX.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.codex"), "prompts"),
            "deploy_agents_dest": os.path.join(os.path.expanduser("~/.codex"), "agents"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.codex"), "skills"),
            "ext": ".md",
            "transform": transform_to_codex,
        },
        "gemini": {
            "check_dir": os.path.expanduser("~/.gemini"),
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "gemini", "GEMINI.md"),
            "commands_dest_dir": os.path.join(dist_dir, "gemini", "commands"),
            "agents_dest_dir": os.path.join(dist_dir, "gemini", "agents"),
            "skills_dest_dir": os.path.join(dist_dir, "gemini", "skills"),
            "skills_ext": ".toml",
            "deploy_master_dest": os.path.join(os.path.expanduser("~/.gemini"), "GEMINI.md"),
            "deploy_commands_dest": os.path.join(os.path.expanduser("~/.gemini"), "commands"),
            "deploy_agents_dest": os.path.join(os.path.expanduser("~/.gemini"), "agents"),
            "deploy_skills_dest": os.path.join(os.path.expanduser("~/.gemini"), "skills"),
            "ext": ".toml",
            "transform": transform_to_gemini,
        },
    }

    artifact_specs: list[FileArtifactType] = [
        FileArtifactType(
            name="agents",
            source_dir_key="agents_dir",
            dest_dir_key="agents_dest_dir",
            deploy_dir_key="deploy_agents_dest",
            ext_key="ext",
            kind="file",
            validator=_validate_agent,
        ),
        FileArtifactType(
            name="commands",
            source_dir_key="commands",
            dest_dir_key="commands_dest_dir",
            deploy_dir_key="deploy_commands_dest",
            ext_key="ext",
            kind="file",
            validator=_validate_command,
        ),
        FileArtifactType(
            name="skills",
            source_dir_key="skills",
            dest_dir_key="skills_dest_dir",
            deploy_dir_key="deploy_skills_dest",
            ext_key="skills_ext",
            kind="skill",
            validator=_validate_skill,
        ),
    ]

    global_sources = []
    if is_mother_project:
        global_sources = [
            {
                "label": "agents",
                "master": master_agents_file,
                "agents_dir": master_agents_dir,
                "commands": master_commands_dir,
                "skills": master_skills_dir,
            }
        ]
    local_sources = [
        {
            "label": ".agents",
            "master": os.path.join(project_root, ".agents", "__none__"),
            "agents_dir": dot_master_agents_dir,
            "commands": dot_master_commands_dir,
            "skills": dot_master_skills_dir,
        },
    ]

    def _existing_sources(source_list: list[dict[str, str]]) -> list[dict[str, str]]:
        existing: list[dict[str, str]] = []
        for source in source_list:
            if source["label"] in {"agents", ".agents"}:
                existing.append(source)
                continue
            if os.path.isfile(source["master"]) or os.path.isdir(source["commands"]) or os.path.isdir(source["skills"]):
                existing.append(source)
        return existing

    global_sources = _existing_sources(global_sources)
    local_sources = _existing_sources(local_sources)

    def _validate_sources(sources: list[dict[str, str]]) -> list[str]:
        errors: list[str] = []
        artifact_items: dict[str, list[str]] = {spec.name: [] for spec in artifact_specs}
        for source in sources:
            for spec in artifact_specs:
                source_dir = source.get(spec.source_dir_key)
                if not isinstance(source_dir, str) or not os.path.isdir(source_dir):
                    continue
                if spec.kind == "file":
                    artifact_items[spec.name].extend([f for f in os.listdir(source_dir) if f.endswith(".md")])
                else:
                    artifact_items[spec.name].extend(
                        [f for f in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, f))]
                    )
        for spec in artifact_specs:
            artifact_items[spec.name] = sorted(set(artifact_items[spec.name]))

        for spec in artifact_specs:
            items = artifact_items[spec.name]
            for item in items:
                item_path = ""
                for source in sources:
                    source_dir = source.get(spec.source_dir_key)
                    if not isinstance(source_dir, str):
                        continue
                    if spec.kind == "file":
                        candidate = os.path.join(source_dir, item)
                    else:
                        candidate = os.path.join(source_dir, item, "SKILL.md")
                    if os.path.exists(candidate):
                        item_path = candidate
                        break
                if not item_path:
                    continue
                try:
                    with open(item_path, "r") as f:
                        post = frontmatter.load(f)
                    spec.validator(post, item_path)
                    if spec.kind == "skill":
                        resolve_skill_name(post, item)
                except Exception as e:
                    errors.append(str(e))
        return errors

    errors: list[str] = []
    errors.extend(_validate_sources(global_sources))
    errors.extend(_validate_sources(local_sources))
    if errors:
        for error in errors:
            print(error)
        if not args.warn_only:
            raise SystemExit(1)
    if validate_only:
        return

    dist_dir = "dist"
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)

    def _run_phase(
        *,
        sources: list[dict[str, str]],
        prefix_root: str,
        dist_dir: str,
        deploy_root: str,
        include_docs: bool,
        emit_repo_codex: bool,
        deploy_enabled: bool,
    ) -> None:
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)
        os.makedirs(dist_dir)

        agent_master_contents: list[str] = []
        markdown_outputs: list[str] = []
        artifact_items: dict[str, list[str]] = {spec.name: [] for spec in artifact_specs}
        for source in sources:
            if os.path.isfile(source["master"]) and source["label"] != ".agents":
                with open(source["master"], "r") as f:
                    agent_master_contents.append(f.read())
            for spec in artifact_specs:
                source_dir = source.get(spec.source_dir_key)
                if not isinstance(source_dir, str) or not os.path.isdir(source_dir):
                    continue
                if spec.kind == "file":
                    artifact_items[spec.name].extend([f for f in os.listdir(source_dir) if f.endswith(".md")])
                else:
                    artifact_items[spec.name].extend(
                        [name for name in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, name))]
                    )
        for spec in artifact_specs:
            artifact_items[spec.name] = sorted(set(artifact_items[spec.name]))

        built_agents: list[str] = []
        for agent_name, config in agents_config.items():
            if agent_name != "agents" and not os.path.isdir(config["check_dir"]):
                print(f"Skipping {agent_name}: directory {config['check_dir']} not found.")
                continue

            print(f"Processing {agent_name}...")

            agent_specific_file = os.path.join(prefix_root, f"PREFIX.{agent_name}.md")
            agent_specific_content = ""
            if os.path.exists(agent_specific_file):
                with open(agent_specific_file, "r") as extra_f:
                    raw_agent_specific = extra_f.read()
                agent_specific_content = process_file(raw_agent_specific, config["prefix"])

            has_any_content = bool(
                agent_master_contents
                or any(artifact_items[spec.name] for spec in artifact_specs)
                or agent_specific_content
            )
            if not has_any_content:
                print(f"Skipping {agent_name}: no agent content found.")
                continue

            master_dest_path = os.path.join(dist_dir, agent_name, os.path.basename(config["master_dest"]))
            processed_contents = [process_file(content, config["prefix"]) for content in agent_master_contents]
            combined_agents_content = "\n\n".join(
                content for content in (agent_specific_content, *processed_contents) if content
            )
            if _should_expand_inline(agent_name) and processed_contents:
                expanded_body = expand_inline_refs(
                    "\n\n".join(content for content in processed_contents if content),
                    project_root=Path(project_root),
                    current_path=Path(project_root) / "AGENTS.md",
                )
                combined_agents_content = "\n\n".join(
                    content for content in (agent_specific_content, expanded_body) if content
                )
            if combined_agents_content:
                master_dest_dir = os.path.dirname(master_dest_path)
                if master_dest_dir:
                    os.makedirs(master_dest_dir, exist_ok=True)
                with open(master_dest_path, "w") as f:
                    f.write(combined_agents_content)
                markdown_outputs.append(master_dest_path)
                if emit_repo_codex and agent_name == "codex":
                    repo_override_path = os.path.join(project_root, "AGENTS.override.md")
                    with open(repo_override_path, "w") as f:
                        f.write(combined_agents_content)
                    markdown_outputs.append(repo_override_path)

            for spec in artifact_specs:
                items = artifact_items[spec.name]
                if not items:
                    continue
                dest_dir = os.path.join(dist_dir, agent_name, os.path.basename(config[spec.dest_dir_key]))
                os.makedirs(dest_dir, exist_ok=True)
                for item in items:
                    item_path = ""
                    for source in sources:
                        source_dir = source.get(spec.source_dir_key)
                        if not isinstance(source_dir, str):
                            continue
                        if spec.kind == "file":
                            candidate = os.path.join(source_dir, item)
                        else:
                            candidate = os.path.join(source_dir, item, "SKILL.md")
                        if os.path.exists(candidate):
                            item_path = candidate
                            break
                    if not item_path:
                        continue
                    with open(item_path, "r") as f:
                        try:
                            post = frontmatter.load(f)
                            spec.validator(post, item_path)
                            prepared = _prepare_post(
                                post,
                                agent_prefix=config["prefix"],
                                agent_name=agent_name,
                                project_root=Path(project_root),
                                current_path=Path(item_path),
                            )
                            if spec.kind == "skill":
                                skill_name = resolve_skill_name(prepared, item)
                                if agent_name == "claude":
                                    transformed_content = transform_skill_to_claude(prepared, skill_name)
                                elif agent_name == "codex":
                                    transformed_content = transform_skill_to_codex(prepared, skill_name)
                                else:
                                    transformed_content = transform_skill_to_gemini(prepared, skill_name)
                                output_dir = os.path.join(dest_dir, item)
                                os.makedirs(output_dir, exist_ok=True)
                                output_filename = f"SKILL{config[spec.ext_key]}"
                                output_path = os.path.join(output_dir, output_filename)
                            else:
                                transformed_content = config["transform"](prepared)
                                base_name = os.path.splitext(item)[0]
                                output_filename = f"{base_name}{config[spec.ext_key]}"
                                output_path = os.path.join(dest_dir, output_filename)
                            with open(output_path, "w") as out_f:
                                out_f.write(transformed_content + "\n")
                            if output_filename.endswith(".md"):
                                markdown_outputs.append(output_path)
                        except Exception as e:
                            print(f"Error processing {spec.name} item {item} for agent {agent_name}: {e}")

            built_agents.append(agent_name)

        if include_docs and os.path.isdir(master_docs_dir):
            docs_dist = os.path.join(dist_dir, "teleclaude", "docs")
            if os.path.exists(docs_dist):
                shutil.rmtree(docs_dist)
            shutil.copytree(master_docs_dir, docs_dist)
            rewrite_global_index(
                os.path.join(docs_dist, "index.yaml"),
                os.path.join(dist_dir, "teleclaude"),
            )

        _format_markdown(markdown_outputs)

        print("\nTranspilation complete.")

        if args.deploy and deploy_enabled:
            print("Deploying files...")
            for agent_name in built_agents:
                config = agents_config[agent_name]

                print(f"Deploying {agent_name}...")

                target_root = os.path.join(deploy_root, os.path.basename(config["check_dir"]))
                os.makedirs(target_root, exist_ok=True)

                dist_agent_root = os.path.join(dist_dir, agent_name)
                shutil.copytree(dist_agent_root, target_root, dirs_exist_ok=True)

            if include_docs and os.path.isdir(master_docs_dir):
                deploy_docs_root = os.path.join(os.path.expanduser("~/.teleclaude"), "docs")

                # Remove old symlink if it exists
                if os.path.islink(deploy_docs_root):
                    os.unlink(deploy_docs_root)

                # Copy docs (overwriting files from this project)
                os.makedirs(deploy_docs_root, exist_ok=True)
                shutil.copytree(master_docs_dir, deploy_docs_root, dirs_exist_ok=True)

                # Merge index.yaml files (combine snippets from multiple projects)
                _merge_global_index(deploy_docs_root)

            print("Deployment complete.")

    if args.deploy:
        with tempfile.TemporaryDirectory(prefix="teleclaude-dist-global-") as global_dist:
            if global_sources:
                _run_phase(
                    sources=global_sources,
                    prefix_root=agents_root,
                    dist_dir=global_dist,
                    deploy_root=os.path.expanduser("~"),
                    include_docs=True,
                    emit_repo_codex=False,
                    deploy_enabled=True,
                )
        with tempfile.TemporaryDirectory(prefix="teleclaude-dist-local-") as local_dist:
            if local_sources:
                _run_phase(
                    sources=local_sources,
                    prefix_root=dot_agents_root,
                    dist_dir=local_dist,
                    deploy_root=project_root,
                    include_docs=False,
                    emit_repo_codex=True,
                    deploy_enabled=True,
                )
    else:
        if global_sources:
            _run_phase(
                sources=global_sources,
                prefix_root=agents_root,
                dist_dir=os.path.join(project_root, "dist", "global"),
                deploy_root=os.path.expanduser("~"),
                include_docs=True,
                emit_repo_codex=False,
                deploy_enabled=False,
            )

        if local_sources:
            _run_phase(
                sources=local_sources,
                prefix_root=dot_agents_root,
                dist_dir=os.path.join(project_root, "dist", "local"),
                deploy_root=project_root,
                include_docs=False,
                emit_repo_codex=True,
                deploy_enabled=False,
            )


if __name__ == "__main__":
    main()
