"""Transpile and deploy agent artifacts and generated documentation."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import NamedTuple, cast
from uuid import uuid4

import frontmatter
import yaml
from frontmatter import Post
from frontmatter.default_handlers import BaseHandler, YAMLHandler
from instrukt_ai_logging import get_logger
from markdown_it import MarkdownIt
from markdown_it.token import Token
from typing_extensions import TypedDict

from teleclaude import agent_artifacts
from teleclaude.artifact_ownership import (
    reconcile_deployed_files,
    retired_pointer_candidate,
    retract_retired_native_artifacts,
)
from teleclaude.capabilities import resolve_capabilities
from teleclaude.constants import ArtifactKind
from teleclaude.core.reconciliation.platform_repository import platform_scope_key
from teleclaude.core.reconciliation.template_installation import template_tree_root
from teleclaude.doc_body import apply_planned_change_sections, apply_planned_sections
from teleclaude.docs_index import write_third_party_index_yaml
from teleclaude.docs_publication import publish_generation
from teleclaude.docs_publishers import (
    DocsPublisherResolutionError,
    DocsResolutionMode,
    Publisher,
    deployed_resolution,
    gather_publishers,
    git_common_root,
    publisher_resolution,
)
from teleclaude.domains import triggers_for_root
from teleclaude.global_skills import compose_global_skill_catalog, global_skill_source_root
from teleclaude.mcp.registry import McpRegistry, load_effective_registry, load_project_declarations, project_mcp_root
from teleclaude.paths import (
    COMMANDS_DIR,
    GLOBAL_DOCS_DIR,
)
from teleclaude.project_manifest import load_roots
from teleclaude.required_reads import extract_required_reads, normalize_required_refs
from teleclaude.resource_validation import INCLUDE_DIRECTIVE_RE, resolve_ref_path, validate_artifact
from teleclaude.session_identity import SessionIdentityMarkerEnvironmentVariable
from teleclaude.snippet_validation import (
    GENERATED_DOMAIN_BUNDLE_FILENAME,
    RETIRED_DOMAIN_BUNDLE_FILENAME,
    SnippetScope,
    derive_snippet_classification,
    generated_domain_bundle_domain,
    load_domains,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")
# The agent runtime's import grammar (third-party/claude-code/instruction-files):
# an ``@`` starting a word, followed by any path up to the first unescaped
# whitespace; a quoted path is not an import. A CommonMark lexer only locates
# the excluded regions (fenced code blocks and code spans); they are masked in
# the raw source and everything else is scanned as written.
_RUNTIME_IMPORT_RE = re.compile(r"(?<!\S)@(?![\"'])((?:\\ |\S)+)")
_MARKDOWN_LEXER = MarkdownIt("commonmark")
_FENCE_TOKEN_TYPE = "fence"
_INLINE_TOKEN_TYPE = "inline"
_INLINE_CODE_TOKEN_TYPE = "code_inline"
_BACKTICK = "`"
_BACKSLASH = "\\"
_SPACE = " "
_MASK = " "
EXEC_DIRECTIVE_RE = re.compile(r"<!--\s*@exec:\s*(.+?)\s*-->")
MCP_INDEX_DIRECTIVE_RE = re.compile(r"<!--\s*@mcp-index\s*-->")
LOCK_SENTINEL_RE = re.compile(r"^[ \t]*<!--\s*/?LOCKED_FILE\b.*?-->[ \t]*\n?", re.MULTILINE | re.DOTALL)
_AGENTS_ENABLED_FLAG = "--agents-enabled"
_DOCS_ENABLED_FLAG = "--docs-enabled"
_AGENTS_ENABLED_HELP = "Enable or disable agent artifact processing."
_DOCS_ENABLED_HELP = "Enable or disable documentation processing."
PROJECT_MASTER_FILENAME = "AGENTS.master.md"
_CODEX_AGENT_NAME = "codex"
_GEMINI_AGENT_NAME = "gemini"
_COMMANDS_STAGING_DIRECTORY = "commands"
UTF8 = "utf-8"
_NEWLINE = "\n"
_SNIPPET_ID_BLOCK = "id: {snippet_id}\n\n{body}"
_SKILL_NAME_FIELD = "name"
_POST_HANDLER_FIELD = "handler"
_MISSING_SKILL_NAME_MESSAGE = "Skill {dirname} is missing frontmatter 'name'"
_SKILL_NAME_MISMATCH_MESSAGE = "Skill name '{name}' must match folder '{dirname}'"
_ARTIFACT_PROCESSING_ERROR = "Error processing {kind} item {item} for agent {agent}: {error}"
_ARTIFACT_DISTRIBUTION_COMPLETED = "artifact_distribution_completed"
_ARTIFACT_DISTRIBUTION_STARTED = "artifact_distribution_started"
_DOMAIN_BASELINE_BUNDLE_GENERATED = "domain_baseline_bundle_generated"
_GENERATED_REQUIRED_READ_EXPANDED = "generated_required_read_expanded"
_INLINE_REF_PREFIX = "@"
_PROJECT_DOCS_RELATIVE_PATH = Path("docs") / "local"
_LOCAL_AGENTS_SOURCE_LABEL = "agents/local"
TIER_PUBLISHED_DOCS_RELATIVE_PATH = Path("docs") / "global"
_MCP_INDEX_HEADER = "## Available MCP Servers\n\n"
_MCP_INDEX_ENTRY_TEMPLATE = "- `{slug}` — {trigger}"
_MCP_INDEX_ENTRY_WITHOUT_TRIGGER_TEMPLATE = "- `{slug}`"
SOURCE_PROJECT_KEY = "source_project"
_SNIPPETS_TREE_NAME = "snippets"
_SNIPPETS_TREE_PATH = Path(_SNIPPETS_TREE_NAME)
_THIRD_PARTY_TREE_NAME = "third-party"
INDEX_FILE_NAME = "index.yaml"
INDEX_SNIPPETS_KEY = "snippets"
_INDEX_ID_KEY = "id"
_INDEX_DOMAIN_KEY = "domain"
INDEX_PROJECT_ROOT_KEY = "project_root"
INDEX_SNIPPETS_ROOT_KEY = "snippets_root"
INDEX_SCOPE_ROOT = "~/.teleclaude"
INDEX_DEPLOY_ROOT = "~/.teleclaude/docs"
_INDEX_SCOPE_KEY = "scope"
TIER_COMPANY_DEPLOY_DIRNAME = "companies"
TIER_PERSON_DEPLOY_DIRNAME = "people"
_COMMITTED_OWNER_COLLISION = "committed publication conflicts with an already deployed snippet id: {snippet_id}"
#: The generated per-domain record of who published a deployed domain and the
#: trigger that publisher declared in the published revision.
_PUBLISHER_RECORD_FILENAME = "publisher.yaml"
_PUBLISHER_RECORD_DOMAIN_KEY = "domain"
_PUBLISHER_RECORD_PUBLISHER_KEY = "publisher"
_PUBLISHER_RECORD_TRIGGER_KEY = "trigger"
_MALFORMED_PUBLISHER_RECORD = "Malformed domain publisher record: {path}"
_UNDECLARED_DOMAIN_TRIGGER = "Publisher '{publisher}' publishes domain '{domain}' without a declared trigger"
_UNRECORDED_DOMAIN_TRIGGERS = (
    "Published domain(s) without a recorded publisher trigger: {domains}; "
    "each publisher must publish its own documentation before the mother's publication can replace the generation"
)
_UNRECORDED_DOMAIN_ENTRY = "{domain} ({publishers})"
_UNKNOWN_PUBLISHER = "unknown publisher"
#: Deployed top-level trees that are not domains: the support fragments and the
#: tier contributions.
_NON_DOMAIN_DEPLOY_DIRNAMES: frozenset[str] = frozenset(
    {_SNIPPETS_TREE_NAME, TIER_COMPANY_DEPLOY_DIRNAME, TIER_PERSON_DEPLOY_DIRNAME}
)
_EMPTY_STRING = ""
_REQUIRED_READ_NOT_FOUND = "Required read not found: {ref}"
_UNRESOLVED_IMPORT = "Generated entrypoint {entrypoint} is not self-contained; it carries imports: {tokens}"
GENERATED_ENTRYPOINT_FILENAME = "AGENTS.md"
_HOME_MASTER_INFLATION_FAILED = "Home master {master} cannot be compiled: {cause}"
HELP_DESK_DIRNAME = "help-desk"
_PUBLICATION_BUILD_RESULT_REQUIRED = "Committed distribution did not return a publication build."
_PUBLICATION_BUILD_STATE_REQUIRED = "Committed distribution requires owned build state."
_PUBLICATION_DOCUMENTATION_TARGET_REQUIRED = "Publication build lost its documentation target."
_GLOBAL_DISTRIBUTION_TEMP_PREFIX = "teleclaude-dist-global-"
_LOCAL_DISTRIBUTION_TEMP_PREFIX = "teleclaude-dist-local-"
_AGENT_CONFIG_HOME_ROOT_KEY = "home_root"
_AGENT_CONFIG_PROJECT_DIR_KEY = "project_dir"
_AGENT_CONFIG_MASTER_DEST_KEY = "master_dest"

logger = get_logger(__name__)


class EntrypointCompositionError(ValueError):
    """A generated agent entrypoint could not be composed from its sources."""


class RequiredReadNotFoundError(EntrypointCompositionError):
    """A required read named by a composed source does not resolve."""

    def __init__(self, ref: str) -> None:
        super().__init__(_REQUIRED_READ_NOT_FOUND.format(ref=ref))
        self.ref = ref


class HomeMasterInflationError(EntrypointCompositionError):
    """A home master could not be compiled into its entrypoint."""

    def __init__(self, master: Path, cause: EntrypointCompositionError) -> None:
        super().__init__(_HOME_MASTER_INFLATION_FAILED.format(master=master, cause=cause))
        self.master = master
        self.cause = cause


class UnresolvedImportError(EntrypointCompositionError):
    """A generated entrypoint's final text still carries runtime import syntax."""

    def __init__(self, entrypoint: Path, tokens: list[str]) -> None:
        super().__init__(_UNRESOLVED_IMPORT.format(entrypoint=entrypoint, tokens=", ".join(tokens)))
        self.entrypoint = entrypoint
        self.tokens = tokens


@dataclass(frozen=True)
class DistributionObservation:
    """Structured event context shared across one deploy-mode distribution."""

    process_correlation_id: str


class PublicationHalves(StrEnum):
    """Which half of a project's publication one distribution performs.

    The published half is what every session reads: the documentation generation and the global agent
    artifacts. The local half is what belongs to the project's own checkout: its project-local agent
    artifacts. The published half alone is what an install publishes on a machine without a platform
    checkout; every commit-boundary and on-demand publication performs both.
    """

    BOTH = "both"
    PUBLISHED = "published"


@dataclass(frozen=True)
class DistributionRequest:
    """Inputs for the internal committed-source distribution operation."""

    project_root: Path
    deploy_root: Path
    deploy: bool
    validate_only: bool = False
    warn_only: bool = False
    agents_enabled: bool | None = None
    docs_enabled: bool | None = None
    preserve_previous_documentation: bool = False
    halves: PublicationHalves = PublicationHalves.BOTH


@dataclass
class DistributionBuildState:
    """Temporary publication resources owned by one committed build."""

    documentation_published: bool = False
    previous_documentation_root: Path | None = None
    documentation_target: Path | None = None
    staging_roots: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class DistributionResult:
    """What one distribution produced for the checkout it was run from.

    ``outputs`` are files written under the project root for installation into
    the canonical checkout; ``retired_pointers`` are the pointer paths beside
    every compiled master, each a candidate for retraction.
    """

    outputs: tuple[Path, ...]
    retired_pointers: tuple[Path, ...]


@dataclass(frozen=True)
class StagedPublicationPhase:
    """One agent phase rendered and waiting for the publication install step."""

    dist_dir: Path
    built_agents: tuple[str, ...]
    deploy_root: str
    is_global_phase: bool
    scope_key: str
    commands_dist_dir: Path


@dataclass
class DistributionBuild:
    """An undoable publication build whose staged effects deploy only on request."""

    result: DistributionResult
    phases: tuple[StagedPublicationPhase, ...]
    agents_config: dict[str, AgentConfig]
    state: DistributionBuildState
    completed: bool = False

    @property
    def outputs(self) -> tuple[Path, ...]:
        return self.result.outputs

    @property
    def retired_pointers(self) -> tuple[Path, ...]:
        return self.result.retired_pointers

    def deploy(self) -> None:
        """Install every rendered phase and finalize the held documentation generation."""
        if self.completed:
            return
        try:
            for phase in self.phases:
                for agent_name in phase.built_agents:
                    config = self.agents_config[agent_name]
                    config_strings = cast(Mapping[str, str], config)
                    target_root = (
                        config_strings[_AGENT_CONFIG_HOME_ROOT_KEY]
                        if phase.is_global_phase
                        else os.path.join(phase.deploy_root, config_strings[_AGENT_CONFIG_PROJECT_DIR_KEY])
                    )
                    _deploy_agent(
                        dist_agent_root=str(phase.dist_dir / agent_name),
                        target_root=target_root,
                    )
                if phase.is_global_phase:
                    shutil.copytree(phase.commands_dist_dir, COMMANDS_DIR, dirs_exist_ok=True)
                    reconcile_deployed_files(scope_key=phase.scope_key, staged_commands_dir=phase.commands_dist_dir)
                retract_retired_native_artifacts(
                    scope_key=phase.scope_key,
                    scope_root=Path(phase.deploy_root),
                    is_global_scope=phase.is_global_phase,
                    replacement_master_written=(
                        phase.dist_dir
                        / _GEMINI_AGENT_NAME
                        / os.path.basename(
                            cast(Mapping[str, str], self.agents_config[_GEMINI_AGENT_NAME])[
                                _AGENT_CONFIG_MASTER_DEST_KEY
                            ]
                        )
                    ).is_file(),
                )
        except Exception:
            _discard_previous_documentation(self.state)
            self._cleanup_staging()
            self.completed = True
            raise
        _discard_previous_documentation(self.state)
        self._cleanup_staging()
        self.completed = True

    def undo(self) -> None:
        """Restore the displaced documentation generation and discard staged output."""
        if self.completed:
            return
        _restore_previous_documentation(self.state)
        self._cleanup_staging()
        self.completed = True

    def _cleanup_staging(self) -> None:
        for root in self.state.staging_roots:
            _remove_publication_path(root)


def distribute_committed(
    project_root: Path,
    canonical_root: Path,
    *,
    agents_enabled: bool,
    docs_enabled: bool,
    halves: PublicationHalves = PublicationHalves.BOTH,
) -> DistributionBuild:
    """Build committed-source artifacts and return an undoable, not-yet-deployed result."""
    original_directory = Path.cwd()
    request = DistributionRequest(
        project_root=project_root,
        deploy_root=canonical_root,
        deploy=True,
        agents_enabled=agents_enabled,
        docs_enabled=docs_enabled,
        preserve_previous_documentation=True,
        halves=halves,
    )
    state = DistributionBuildState()
    try:
        result = main(request, build_state=state)
    except BaseException:
        _restore_previous_documentation(state)
        for staging_root in state.staging_roots:
            _remove_publication_path(staging_root)
        raise
    finally:
        os.chdir(original_directory)
    if not isinstance(result, DistributionBuild):
        raise TypeError(_PUBLICATION_BUILD_RESULT_REQUIRED)
    return result


def _restore_previous_documentation(state: DistributionBuildState) -> None:
    """Restore the generation displaced by an incomplete committed build."""
    if not state.documentation_published:
        return
    target = state.documentation_target
    if target is None:
        raise RuntimeError(_PUBLICATION_DOCUMENTATION_TARGET_REQUIRED)
    previous = state.previous_documentation_root
    if previous is None:
        _remove_publication_path(target)
    else:
        displaced = publish_generation(previous, target)
        if displaced is not None:
            _remove_publication_path(displaced)
    state.documentation_published = False
    state.previous_documentation_root = None


def _discard_previous_documentation(state: DistributionBuildState) -> None:
    """Discard the old generation after publication effects have completed."""
    previous = state.previous_documentation_root
    if previous is not None:
        _remove_publication_path(previous)
    state.documentation_published = False
    state.previous_documentation_root = None


def _remove_publication_path(path: Path) -> None:
    """Remove a temporary publication root, including a symlink root."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


_APPENDED_SECTION_TEMPLATE = "{content}\n\n---\n\n{sections}\n"


class StableYAMLHandler(YAMLHandler):  # type: ignore[misc]
    """Frontmatter YAML handler with stable ordering and wide line width."""

    def export(self, metadata: dict[str, object], **kwargs: object) -> str:  # guard: loose-dict - frontmatter contract
        return yaml.safe_dump(  # type: ignore[no-any-return]
            metadata,
            sort_keys=False,
            width=1000,
            default_flow_style=False,
            allow_unicode=True,
        ).rstrip()


_FRONTMATTER_HANDLER = StableYAMLHandler()


def dump_frontmatter(post: Post) -> str:
    """Serialize frontmatter using the stable YAML handler."""
    return str(frontmatter.dumps(post, handler=_FRONTMATTER_HANDLER))


class SnippetIndexEntry(TypedDict, total=False):
    """Snippet entry loaded from docs index.yaml."""

    id: str
    description: str
    type: str
    scope: str
    domain: str
    activation_trigger: str | None
    subscriptions: list[str]
    path: str


class ActivatableEntry(NamedTuple):
    """A triggered procedure auto-collected for one agent-output scope."""

    snippet_id: str
    description: str
    trigger: str


class ConfiguredResponsibilityEntry(NamedTuple):
    """A subscribed procedure auto-collected for one agent-output scope."""

    snippet_id: str
    description: str
    events: tuple[str, ...]


class DomainScope(NamedTuple):
    """Collect a single domain's triggered procedures from the merged deploy index."""

    domain: str


class ProjectScope(NamedTuple):
    """Collect the project's own scope-local triggered procedures."""


# Tagged union discriminating which activatable procedures a surface collects:
# a single domain's, or the project's own.
ActivatableScope = DomainScope | ProjectScope


class AgentConfig(TypedDict):
    """Agent-specific output and deploy paths."""

    home_root: str
    project_dir: str
    prefix: str
    master_dest: str
    skills_dest_dir: str
    skills_ext: str


class FileArtifactType(NamedTuple):
    """Artifact type metadata for source, dist, and deploy phases."""

    name: str
    source_dir_key: str
    dest_dir_key: str
    ext_key: str
    artifact_kind: ArtifactKind


def _deploy_agent(
    *,
    dist_agent_root: str,
    target_root: str,
) -> None:
    """Mirror one agent's staged artifacts into its deployment root."""
    os.makedirs(target_root, exist_ok=True)
    shutil.copytree(dist_agent_root, target_root, dirs_exist_ok=True)


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
    transformed_post = _post_with_metadata(post.content, metadata)
    content = dump_frontmatter(transformed_post)
    return content


def transform_skill_to_gemini(post: Post, name: str) -> str:
    """Transform a skill post to Gemini SKILL.md format.

    Same YAML frontmatter as Claude but strips hooks (not supported by Gemini).
    """
    metadata = {"name": name, "description": post.metadata.get("description", "")}
    # Preserve any other metadata except hooks (Gemini doesn't support them)
    for key, value in post.metadata.items():
        if key not in ("name", "description", "hooks"):
            metadata[key] = value
    transformed_post = _post_with_metadata(post.content, metadata)
    return dump_frontmatter(transformed_post)


def transform_skill_to_deepseek(post: Post, name: str) -> str:
    """Transform a skill post to the DSH SKILL.md shape (plain frontmatter)."""
    description = post.metadata.get("description", "")
    transformed_post = Post(post.content, name=name, description=description)
    return dump_frontmatter(transformed_post)


def _should_expand_inline(agent_name: str) -> bool:
    return agent_name in {"claude", "codex", "gemini", "deepseek"}


# guard: loose-dict-func - Open frontmatter keys vary by artifact kind
def _filter_frontmatter(metadata: Mapping[str, object], agent_name: str) -> dict[str, object]:
    filtered = dict(metadata)
    if agent_name != "claude":
        filtered.pop("hooks", None)
    return filtered


def _post_with_metadata(content: str, metadata: Mapping[str, object]) -> Post:
    """Preserve open artifact fields without treating metadata as Post's handler argument."""
    copied_metadata = dict(metadata)
    handler = copied_metadata.pop(_POST_HANDLER_FIELD, None)
    post = Post(content, handler=handler if isinstance(handler, BaseHandler) else None)
    post.metadata.update(copied_metadata)
    return post


def _is_pending(metadata: Mapping[str, object]) -> bool:
    """Whether a snippet declares an undelivered contract via ``delivered_by``.

    The single pending test for every transpiled surface, applied to an index
    entry or to a snippet's own frontmatter alike. A pending snippet describes
    behavior that does not exist yet, so it is invisible to agent-facing output
    until the integrator clears the field at delivery.
    """
    delivered_by = metadata.get("delivered_by")
    return isinstance(delivered_by, list) and bool(delivered_by)


def _load_index_entries(index_path: Path) -> dict[str, SnippetIndexEntry]:
    entries: dict[str, SnippetIndexEntry] = {}
    if not index_path.exists():
        return entries
    payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return entries
    snippets = payload.get("snippets")
    if not isinstance(snippets, list):
        return entries
    for item in snippets:
        if not isinstance(item, dict):
            continue
        snippet_id = item.get("id")
        if isinstance(snippet_id, str):
            entries[snippet_id] = cast(SnippetIndexEntry, dict(item))
    return entries


def _load_snippet_index_entries(project_root: Path) -> dict[str, SnippetIndexEntry]:
    entries: dict[str, SnippetIndexEntry] = {}
    for index_path in (
        project_root / "docs" / "global" / "index.yaml",
        project_root / _PROJECT_DOCS_RELATIVE_PATH / "index.yaml",
    ):
        entries.update(_load_index_entries(index_path))
    return entries


def _index_entry_for_path(
    path: Path,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry],
) -> SnippetIndexEntry | None:
    logical_path = _logical_snippet_path(path, project_root=project_root)
    classification, _ = derive_snippet_classification(
        logical_path, project_root=project_root, domains=load_domains(project_root)
    )
    if classification is None:
        return None
    return entries_by_id.get(classification.id)


def _logical_snippet_path(path: Path, *, project_root: Path) -> Path:
    """Return a project-local logical snippet path for deployed global refs."""
    try:
        path.resolve().relative_to(project_root.resolve())
        return path
    except ValueError:
        pass

    parts = path.resolve().parts
    for scope in ("global", "local"):
        marker = ("docs", scope)
        for index in range(len(parts) - 1):
            if parts[index : index + 2] != marker:
                continue
            tail = Path(*parts[index + 2 :])
            return project_root / "docs" / scope / tail
    return path


def _prepare_post(
    post: Post,
    *,
    agent_prefix: str,
    agent_name: str,
    project_root: Path,
    current_path: Path,
    warn_only: bool,
    observation: DistributionObservation | None,
) -> Post:
    content = process_file(post.content, agent_prefix, agent_name)
    if _should_expand_inline(agent_name):
        content = expand_inline_refs(
            content,
            project_root=project_root,
            current_path=current_path,
            warn_only=warn_only,
            observation=observation,
        )
    metadata = _filter_frontmatter(post.metadata, agent_name)
    return _post_with_metadata(content, metadata)


def resolve_skill_name(post: Post, dirname: str) -> str:
    """Resolve the skill name from metadata and validate its directory."""
    name = cast(str, post.metadata.get(_SKILL_NAME_FIELD))
    if not name:
        raise ValueError(_MISSING_SKILL_NAME_MESSAGE.format(dirname=dirname))
    if name != dirname:
        raise ValueError(_SKILL_NAME_MISMATCH_MESSAGE.format(name=name, dirname=dirname))
    return name


def process_file(content: str, agent_prefix: str, agent_name: str) -> str:
    """Apply substitutions to the file content."""
    content = content.replace("{AGENT_PREFIX}", agent_prefix)
    content = content.replace("{{agent}}", agent_name)
    return content


def _scope_label(scope: ActivatableScope) -> str:
    """Human-facing name of the surface a rendered section belongs to."""
    if isinstance(scope, DomainScope):
        return "Domain"
    return "Project"


def _render_progressive_index_section(entries: list[str], scope: ActivatableScope) -> str:
    header = f"## {_scope_label(scope)} baseline index — load via `telec docs get <id>` when relevant\n\n"
    return header + "\n".join(entries)


def _render_activatable_procedures_section(activatable_entries: list[ActivatableEntry]) -> str:
    if not activatable_entries:
        return ""
    sorted_entries = sorted(activatable_entries, key=lambda entry: entry.snippet_id)
    lines = [f"- `{entry.snippet_id}` — {entry.description} — {entry.trigger}" for entry in sorted_entries]
    header = "## Activatable Procedures — load via `telec docs get <id> --closure` before acting\n\n"
    return header + "\n".join(lines)


def _render_configured_responsibilities_section(configured_entries: list[ConfiguredResponsibilityEntry]) -> str:
    if not configured_entries:
        return ""
    sorted_entries = sorted(configured_entries, key=lambda entry: entry.snippet_id)
    lines = [
        f"- `{entry.snippet_id}` — {entry.description} — answers: {', '.join(entry.events)}" for entry in sorted_entries
    ]
    header = "## Configured Responsibilities — started by the platform when their events arrive\n\n"
    return header + "\n".join(lines)


def _activatable_entry_from_index(entry: SnippetIndexEntry) -> ActivatableEntry | None:
    """Construct an :class:`ActivatableEntry` from an index entry, or ``None`` if not activatable.

    This is the single construction site for activatable entries: an entry is
    activatable only when it is a ``procedure`` carrying a non-empty
    ``activation_trigger`` and no pending ``delivered_by``. A triggered
    procedure missing its ``description`` fails fast (never silently dropped) so
    an incomplete entry can never reach a rendered section.
    """
    if entry.get("type") != "procedure":
        return None
    if _is_pending(entry):
        return None
    trigger = entry.get("activation_trigger")
    if not isinstance(trigger, str) or not trigger.strip():
        return None
    snippet_id = entry.get("id")
    if not isinstance(snippet_id, str) or not snippet_id:
        return None
    description = entry.get("description")
    if not isinstance(description, str) or not description:
        raise ValueError(f"Triggered procedure is missing a description: {snippet_id}")
    return ActivatableEntry(snippet_id=snippet_id, description=description, trigger=trigger.strip())


def _configured_responsibility_from_index(entry: SnippetIndexEntry) -> ConfiguredResponsibilityEntry | None:
    """Construct a :class:`ConfiguredResponsibilityEntry` from an index entry, or ``None`` if not subscribed.

    An entry is a configured responsibility only when it is a ``procedure``
    carrying a non-empty ``subscriptions`` list and no pending
    ``delivered_by``. A subscribed procedure missing its ``description``
    fails fast, exactly like its activatable twin.
    """
    if entry.get("type") != "procedure":
        return None
    if _is_pending(entry):
        return None
    subscriptions = entry.get("subscriptions")
    if not isinstance(subscriptions, list) or not subscriptions:
        return None
    snippet_id = entry.get("id")
    if not isinstance(snippet_id, str) or not snippet_id:
        return None
    description = entry.get("description")
    if not isinstance(description, str) or not description:
        raise ValueError(f"Subscribed procedure is missing a description: {snippet_id}")
    return ConfiguredResponsibilityEntry(snippet_id=snippet_id, description=description, events=tuple(subscriptions))


def _scope_filtered_source_entries(
    scope: ActivatableScope,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
) -> list[SnippetIndexEntry]:
    """Resolve a scope's candidate index entries, shared by every auto-collector.

    ``DomainScope`` filters the merged deploy index (``entries_by_id``) to one
    domain. ``ProjectScope`` filters the project's own index load to
    ``scope == "project"`` — that loader returns both project- and
    local-global-scoped entries, and unfiltered collection would leak the
    latter.
    """
    if isinstance(scope, DomainScope):
        candidates = (entries_by_id or {}).values()
        return [entry for entry in candidates if entry.get("domain") == scope.domain]
    return [entry for entry in _load_snippet_index_entries(project_root).values() if entry.get("scope") == "project"]


def _discover_activatables(
    scope: ActivatableScope,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
) -> list[ActivatableEntry]:
    """Discover a scope's triggered procedures from index declarations, never a manifest."""
    source_entries = _scope_filtered_source_entries(scope, project_root=project_root, entries_by_id=entries_by_id)
    collected = (_activatable_entry_from_index(entry) for entry in source_entries)
    return [entry for entry in collected if entry is not None]


def _discover_configured_responsibilities(
    scope: ActivatableScope,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
) -> list[ConfiguredResponsibilityEntry]:
    """Discover a scope's subscribed procedures from index declarations, never a manifest."""
    source_entries = _scope_filtered_source_entries(scope, project_root=project_root, entries_by_id=entries_by_id)
    collected = (_configured_responsibility_from_index(entry) for entry in source_entries)
    return [entry for entry in collected if entry is not None]


def _collect_baseline_index_entries(
    ref_file: Path,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
    warn_only: bool = False,
) -> list[str]:
    """Collect a ``baseline-progressive.md`` manifest's curated Baseline index entries.

    Manifests curate; frontmatter declares. A curated ref that resolves to a
    triggered procedure is dead weight — auto-inclusion via :func:`_discover_activatables`
    already surfaces it — so the sync blocks unconditionally on it: agent-facing
    checks have no warn-and-pass tier, and ``warn_only`` never downgrades this
    check.

    A curated ref that resolves to a pending snippet is skipped rather than
    blocked: the manifest names the contract the snippet will carry, and the
    entry renders itself once delivery clears ``delivered_by``.
    """
    content = ref_file.read_text(encoding="utf-8")
    baseline_entries: list[str] = []
    entries_by_id = entries_by_id or _load_snippet_index_entries(project_root)

    for match in INLINE_REF_RE.finditer(content):
        ref = match.group(1)
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=ref_file)
        if not resolved or not resolved.exists():
            if warn_only:
                print(f"WARNING: Progressive index ref not found: {ref}")
                continue
            raise ValueError(f"Progressive index ref not found: {ref}")

        entry = _index_entry_for_path(resolved, project_root=project_root, entries_by_id=entries_by_id)
        if entry is None:
            if warn_only:
                print(f"WARNING: Progressive index ref missing from index: {ref}")
                continue
            raise ValueError(f"Progressive index ref missing from index: {ref}")
        if _is_pending(entry):
            continue
        snippet_id = entry.get("id")
        description = entry.get("description")
        snippet_type = entry.get("type")
        activation_trigger = entry.get("activation_trigger")
        subscriptions = entry.get("subscriptions")

        if snippet_type == "procedure" and isinstance(activation_trigger, str) and activation_trigger.strip():
            try:
                manifest_display = ref_file.relative_to(project_root)
            except ValueError:
                manifest_display = ref_file
            raise ValueError(
                "Triggered procedure is auto-included via its frontmatter; remove it from the manifest: "
                f"{manifest_display} lists {ref}"
            )

        if snippet_type == "procedure" and isinstance(subscriptions, list) and subscriptions:
            try:
                manifest_display = ref_file.relative_to(project_root)
            except ValueError:
                manifest_display = ref_file
            raise ValueError(
                "Subscribed procedure is auto-included via its frontmatter; remove it from the manifest: "
                f"{manifest_display} lists {ref}"
            )

        if isinstance(snippet_id, str) and isinstance(description, str) and description:
            baseline_entries.append(f"- `{snippet_id}` — {description}")
        elif isinstance(snippet_id, str) and snippet_id:
            baseline_entries.append(f"- `{snippet_id}`")

    return baseline_entries


def _progressive_sibling_sections(
    base_dir: Path,
    *,
    scope: ActivatableScope,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
    warn_only: bool = False,
) -> str:
    """Render one surface's sibling ``baseline-progressive.md`` sections.

    The sibling is detected by location — ``base_dir / "baseline-progressive.md"``
    — never by a Source ``@``-ref; returns ``""`` when it does not exist. Renders
    the manifest's curated Baseline index, then the scope's activatable
    procedures, then its configured responsibilities — both auto-collected
    from index declarations. This is the single routine every surface (domain
    bundle, project ``AGENTS.md``) calls; only the scope differs per caller. A
    global agent config receives the ``general`` domain's sections through its
    inlined ``general`` bundle.
    """
    progressive_src = base_dir / "baseline-progressive.md"
    if not progressive_src.exists():
        return ""
    baseline_entries = _collect_baseline_index_entries(
        progressive_src, project_root=project_root, entries_by_id=entries_by_id, warn_only=warn_only
    )
    activatable_entries = _discover_activatables(scope, project_root=project_root, entries_by_id=entries_by_id)
    configured_entries = _discover_configured_responsibilities(
        scope, project_root=project_root, entries_by_id=entries_by_id
    )
    blocks = [
        block
        for block in (
            _render_progressive_index_section(baseline_entries, scope) if baseline_entries else "",
            _render_activatable_procedures_section(activatable_entries),
            _render_configured_responsibilities_section(configured_entries),
        )
        if block
    ]
    return "\n\n".join(blocks)


def _exec_directive_env(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    for marker_variable in SessionIdentityMarkerEnvironmentVariable:
        env.pop(marker_variable, None)
    path_entries = [
        str(project_root / ".venv" / "bin"),
        str(_REPO_ROOT / ".venv" / "bin"),
    ]
    existing_path = env.get("PATH", "")
    if existing_path:
        path_entries.extend(existing_path.split(os.pathsep))
    deduped_entries: list[str] = []
    seen_entries: set[str] = set()
    for entry in path_entries:
        if not entry or entry in seen_entries:
            continue
        seen_entries.add(entry)
        deduped_entries.append(entry)
    env["PATH"] = os.pathsep.join(deduped_entries)
    return env


# Process-lifetime cache: ``@exec`` commands are pure CLI help-text invocations
# that re-running within one distribution run cannot change. The same set
# of directives is expanded once per agent (claude/codex/gemini/deepseek) and
# once per phase (global + local), so without caching the same ``telec -h``-style
# subprocess fires 20-30+ times and dominates wall time.
_EXEC_DIRECTIVE_CACHE: dict[tuple[str, str], str | None] = {}


def expand_exec_directives(content: str, *, project_root: Path, warn_only: bool = False) -> str:
    """Expand ``<!-- @exec: command -->`` directives by running the command and inserting stdout."""

    def _run(match: re.Match[str]) -> str:
        cmd = match.group(1)
        cache_key = (str(project_root), cmd)
        cached = _EXEC_DIRECTIVE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=project_root,
                env=_exec_directive_env(project_root),
                check=False,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                msg = f"@exec failed ({result.returncode}): {cmd}"
                if warn_only:
                    print(f"WARNING: {msg}")
                    rendered = match.group(0)
                    _EXEC_DIRECTIVE_CACHE[cache_key] = rendered
                    return rendered
                raise RuntimeError(msg)
            rendered = "" if not output else f"```\n{output}\n```"
            _EXEC_DIRECTIVE_CACHE[cache_key] = rendered
            return rendered
        except subprocess.TimeoutExpired:
            msg = f"@exec timed out: {cmd}"
            if warn_only:
                print(f"WARNING: {msg}")
                rendered = match.group(0)
                _EXEC_DIRECTIVE_CACHE[cache_key] = rendered
                return rendered
            raise RuntimeError(msg) from None

    return EXEC_DIRECTIVE_RE.sub(_run, content)


def expand_include_directives(
    content: str,
    *,
    project_root: Path,
    current_path: Path,
    warn_only: bool = False,
) -> str:
    """Expand ``<!-- @include: path.md -->`` directives by inlining the snippet body at that point.

    Unlike a ``## Required reads`` ``@``-ref — which is hoisted to the top of the
    compiled artifact — an ``@include`` lands the snippet exactly where the comment
    sits, keeping the content adjacent to the instruction that needs it. The
    included body is recursively expanded so it may itself carry ``@``-refs.
    """

    def _render(match: re.Match[str]) -> str:
        ref = match.group(1)
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
        if not resolved or not resolved.exists():
            msg = f"@include not found: {ref}"
            if warn_only:
                print(f"WARNING: {msg}")
                return match.group(0)
            raise ValueError(msg)
        post = frontmatter.loads(resolved.read_text(encoding="utf-8"))
        return expand_inline_refs(
            post.content,
            project_root=project_root,
            current_path=resolved,
            warn_only=warn_only,
        ).strip()

    return INCLUDE_DIRECTIVE_RE.sub(_render, content)


def _snippet_body(resolved: Path, *, expand: Callable[[str, Path], str]) -> str | None:
    """Recursively-expanded body of a resolved snippet, or ``None`` when pending.

    The single inlining gate: a snippet whose frontmatter declares
    ``delivered_by`` describes behavior that does not exist yet, so its body
    never reaches a transpiled surface. Both ref paths — curated ``@``-refs and
    required reads — resolve their bodies here, so one check covers both.
    """
    post = frontmatter.loads(resolved.read_text(encoding="utf-8"))
    if _is_pending(post.metadata):
        return None
    return expand(post.content, resolved).strip()


def _snippet_id_for_path(path: Path, *, project_root: Path, domains: set[str]) -> str | None:
    """Canonical snippet id for a resolved path, or ``None`` when unclassifiable."""
    logical_path = _logical_snippet_path(path, project_root=project_root)
    classification, _ = derive_snippet_classification(logical_path, project_root=project_root, domains=domains)
    return classification.id if classification else None


def expand_inline_refs(
    content: str,
    *,
    project_root: Path,
    current_path: Path,
    warn_only: bool = False,
    observation: DistributionObservation | None = None,
) -> str:
    """Inline @path.md references into the content (Codex speedup).

    A ``@``-ref always means exactly one thing: expand verbatim. Progressive
    disclosure is never driven by a ref — it is rendered separately by
    :func:`_progressive_sibling_sections`, keyed to the sibling file's
    location on disk, not to any Source reference.
    """
    seen: set[Path] = set()
    domains = load_domains(project_root)

    def _expand_document(text: str, *, current_path: Path, depth: int) -> str:
        if depth <= 0:
            return text

        # Mirror the reader contract (context_selector.py): a plain read drops pending
        # planned blocks so baselines ground in current truth, not unbuilt behavior.
        text = apply_planned_change_sections(text, None)
        text = apply_planned_sections(text, None)

        required_refs, stripped = extract_required_reads(text)
        required_refs = normalize_required_refs(required_refs)
        required_sections: list[str] = []
        for ref in required_refs:
            resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
            if not resolved or not resolved.exists():
                if warn_only:
                    print(f"WARNING: {_REQUIRED_READ_NOT_FOUND.format(ref=ref)}")
                    continue
                raise RequiredReadNotFoundError(ref)
            if resolved in seen:
                continue
            seen.add(resolved)

            body = _snippet_body(
                resolved,
                expand=lambda text, cur: _expand_document(text, current_path=cur, depth=depth - 1),
            )
            if body is None:
                continue
            generated_bundle_domain = generated_domain_bundle_domain(f"{_INLINE_REF_PREFIX}{ref}", domains=domains)
            if generated_bundle_domain is not None and observation is not None:
                logger.info(
                    _GENERATED_REQUIRED_READ_EXPANDED,
                    process_correlation_id=observation.process_correlation_id,
                    domain=generated_bundle_domain,
                    consumer_name=current_path.name,
                )
            expanded = _strip_leading_separators(_strip_specific_h1(body, "Project baseline").strip())
            if expanded:
                required_sections.append(expanded)

        def _replace(match: re.Match[str]) -> str:
            ref = match.group(1)
            resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
            if not resolved or not resolved.exists():
                return match.group(0)
            if resolved in seen:
                return ""
            seen.add(resolved)

            body = _snippet_body(
                resolved,
                expand=lambda text, cur: _expand_document(text, current_path=cur, depth=depth - 1),
            )
            if body is None:
                return ""
            if resolved.name == "index.md":
                return f"{body}\n" if body else ""
            expanded = _strip_leading_separators(_strip_specific_h1(body, "Project baseline").strip())
            return f"---\n\n{expanded}\n" if expanded else ""

        expanded_body = INLINE_REF_RE.sub(_replace, stripped)
        expanded_body = _strip_leading_separators(expanded_body)
        snippet_id = _snippet_id_for_path(current_path, project_root=project_root, domains=domains)
        if snippet_id and expanded_body.strip():
            expanded_body = _SNIPPET_ID_BLOCK.format(snippet_id=snippet_id, body=expanded_body)
        if required_sections:
            required_block = "\n\n---\n\n".join(required_sections).strip()
            if expanded_body.strip():
                return f"{required_block}\n\n---\n\n{expanded_body}"
            return required_block
        return expanded_body

    expanded = _expand_document(content, current_path=current_path, depth=20)
    return _expand_point_directives(expanded, project_root=project_root, current_path=current_path, warn_only=warn_only)


def _expand_point_directives(
    content: str,
    *,
    project_root: Path,
    current_path: Path,
    warn_only: bool = False,
) -> str:
    """Run the in-place directive passes (``@include`` then ``@exec``) over expanded content."""
    if INCLUDE_DIRECTIVE_RE.search(content):
        content = expand_include_directives(
            content, project_root=project_root, current_path=current_path, warn_only=warn_only
        )
    if EXEC_DIRECTIVE_RE.search(content):
        content = expand_exec_directives(content, project_root=project_root, warn_only=warn_only)
    if MCP_INDEX_DIRECTIVE_RE.search(content):
        content = _expand_mcp_index_directives(content)
    return content


def _expand_mcp_index_directives(content: str) -> str:
    """Render the machine-wide MCP index in global agent-facing sources."""
    registry = load_effective_registry(git_common_root(_REPO_ROOT))
    return MCP_INDEX_DIRECTIVE_RE.sub(lambda _match: _render_mcp_index(registry), content)


def _render_mcp_index(registry: McpRegistry) -> str:
    """Render visible enabled server declarations with their activation triggers."""
    lines: list[str] = []
    for server in registry.enabled_servers():
        if server.hidden:
            continue
        if server.trigger is None or not server.trigger.strip():
            lines.append(_MCP_INDEX_ENTRY_WITHOUT_TRIGGER_TEMPLATE.format(slug=server.slug))
            continue
        lines.append(_MCP_INDEX_ENTRY_TEMPLATE.format(slug=server.slug, trigger=server.trigger.strip()))
    return _MCP_INDEX_HEADER + _NEWLINE.join(lines) if lines else ""


def _inflate_domain_baseline(
    baseline_src: Path,
    domain_src: Path,
    *,
    project_root: Path,
    entries_by_id: dict[str, SnippetIndexEntry] | None = None,
) -> str:
    """Inflate a baseline manifest and append its sibling progressive sections.

    The generic baseline-assembly routine, shared by every scope that owns a
    baseline: fully expands ``baseline.md``, then — when a sibling
    ``baseline-progressive.md`` exists — appends the load-on-demand baseline
    index and any activatable procedures declared there. The progressive sibling
    is optional; where there is a baseline, there is usually (not necessarily) a
    progressive alongside it.
    """
    inflated = expand_inline_refs(
        baseline_src.read_text(encoding="utf-8"),
        project_root=project_root,
        current_path=baseline_src,
    )
    sections = _progressive_sibling_sections(
        domain_src,
        scope=DomainScope(domain_src.name),
        project_root=project_root,
        entries_by_id=entries_by_id,
    )
    if sections:
        inflated = f"{inflated.rstrip()}\n\n---\n\n{sections}\n"
    return inflated


class DomainPublisherRecord(NamedTuple):
    """Who published one deployed domain, and the trigger declared in that revision."""

    domain: str
    publisher: str
    trigger: str


class UnrecordedDomainTriggerError(ValueError):
    """A published domain reached the mother's publication without a recorded trigger."""


def _write_domain_publisher_record(staged_domain: Path, *, domain: str, publisher: Publisher, trigger: str) -> None:
    """Write the record of a domain's publisher beside its staged bodies."""
    (staged_domain / _PUBLISHER_RECORD_FILENAME).write_text(
        yaml.safe_dump(
            {
                _PUBLISHER_RECORD_DOMAIN_KEY: domain,
                _PUBLISHER_RECORD_PUBLISHER_KEY: publisher.slug,
                _PUBLISHER_RECORD_TRIGGER_KEY: trigger,
            },
            sort_keys=False,
            width=1000,
            allow_unicode=True,
        ),
        encoding=UTF8,
    )


def _declared_trigger(triggers: Mapping[str, str], *, domain: str, publisher: Publisher) -> str:
    """Return the trigger a publisher declared for a domain it publishes, or fail fast."""
    trigger = triggers.get(domain)
    if trigger is None:
        raise ValueError(_UNDECLARED_DOMAIN_TRIGGER.format(publisher=publisher.slug, domain=domain))
    return trigger


def _read_domain_publisher_records(docs_root: Path) -> dict[str, DomainPublisherRecord]:
    """Read every domain's publisher record in one documentation generation."""
    records: dict[str, DomainPublisherRecord] = {}
    if not docs_root.is_dir():
        return records
    for record_path in sorted(docs_root.glob(f"*/{_PUBLISHER_RECORD_FILENAME}")):
        payload = yaml.safe_load(record_path.read_text(encoding=UTF8))
        if not isinstance(payload, dict):
            raise ValueError(_MALFORMED_PUBLISHER_RECORD.format(path=record_path))
        domain = payload.get(_PUBLISHER_RECORD_DOMAIN_KEY)
        publisher = payload.get(_PUBLISHER_RECORD_PUBLISHER_KEY)
        trigger = payload.get(_PUBLISHER_RECORD_TRIGGER_KEY)
        if (
            not isinstance(domain, str)
            or domain != record_path.parent.name
            or not isinstance(publisher, str)
            or not publisher
            or not isinstance(trigger, str)
            or not trigger.strip()
        ):
            raise ValueError(_MALFORMED_PUBLISHER_RECORD.format(path=record_path))
        records[domain] = DomainPublisherRecord(domain=domain, publisher=publisher, trigger=trigger)
    return records


def _live_global_entries(docs_root: Path) -> list[SnippetIndexEntry]:
    """Return a generation's non-pending global-scope merged-index entries."""
    return [
        entry
        for entry in _load_index_entries(docs_root / INDEX_FILE_NAME).values()
        if entry.get(_INDEX_SCOPE_KEY) == SnippetScope.GLOBAL.value and not _is_pending(entry)
    ]


def _require_domain_publisher_records(staged_root: Path) -> None:
    """Fail before replacing a generation when a published domain carries no record."""
    records = _read_domain_publisher_records(staged_root)
    unrecorded: dict[str, set[str]] = {}
    for entry in _live_global_entries(staged_root):
        domain = entry.get(_INDEX_DOMAIN_KEY)
        if not isinstance(domain, str) or domain in records:
            continue
        publisher = entry.get(SOURCE_PROJECT_KEY)
        unrecorded.setdefault(domain, set()).add(publisher if isinstance(publisher, str) else _UNKNOWN_PUBLISHER)
    if unrecorded:
        named = ", ".join(
            _UNRECORDED_DOMAIN_ENTRY.format(domain=domain, publishers=", ".join(sorted(unrecorded[domain])))
            for domain in sorted(unrecorded)
        )
        raise UnrecordedDomainTriggerError(_UNRECORDED_DOMAIN_TRIGGERS.format(domains=named))


def _retire_carried_over_bundles(staged_root: Path, *, owned_domains: set[str]) -> None:
    """Retire the legacy bundle name in every domain this publication carries over.

    A carried-over domain keeps the bytes its consumers read today: the legacy
    file becomes the generated bundle when none exists, and is removed when one
    does. The current publisher's domains are rebuilt from its snapshot.
    """
    for staged_domain in sorted(path for path in staged_root.iterdir() if path.is_dir()):
        if staged_domain.name in owned_domains or staged_domain.name in _NON_DOMAIN_DEPLOY_DIRNAMES:
            continue
        legacy = staged_domain / RETIRED_DOMAIN_BUNDLE_FILENAME
        if not legacy.is_file():
            continue
        bundle = staged_domain / GENERATED_DOMAIN_BUNDLE_FILENAME
        if bundle.exists():
            legacy.unlink()
        else:
            legacy.rename(bundle)


def _copy_domain_without_retired_bundle(source_domain: Path, staged_domain: Path) -> None:
    """Copy one domain tree into a generation, leaving out a retired-name bundle at its root.

    A publisher checkout may still hold the retired generator's output — as an
    ignored leftover or a tracked file — and it never enters a generation; a
    file of that name deeper in the tree is an ordinary snippet.
    """

    def ignore_retired_bundle(directory: str, names: list[str]) -> list[str]:
        if Path(directory) == source_domain and RETIRED_DOMAIN_BUNDLE_FILENAME in names:
            return [RETIRED_DOMAIN_BUNDLE_FILENAME]
        return []

    shutil.copytree(source_domain, staged_domain, symlinks=False, ignore=ignore_retired_bundle)


def committed_retired_outputs(project_root: Path) -> list[Path]:
    """Return the publisher-checkout outputs a retired generator wrote for a snapshot.

    Each is a ``docs/global/<domain>/`` legacy bundle the snapshot does not
    track; the caller retracts from the canonical checkout only those the
    checkout holds as ignored, untracked files. A tracked file of that name is
    the project's own and is never reported.
    """
    docs_global = project_root / TIER_PUBLISHED_DOCS_RELATIVE_PATH
    if not docs_global.is_dir():
        return []
    return [
        domain_dir / RETIRED_DOMAIN_BUNDLE_FILENAME
        for domain_dir in sorted(path for path in docs_global.iterdir() if path.is_dir())
        if not (domain_dir / RETIRED_DOMAIN_BUNDLE_FILENAME).exists()
    ]


def materialize_docs_root(owner_by_domain: dict[str, Publisher], staged_root: Path) -> None:
    """Copy every registered domain, with its publisher record, into one staged generation."""
    copied = 0
    triggers_by_publisher: dict[str, dict[str, str]] = {}
    for domain in sorted(owner_by_domain):
        owner = owner_by_domain[domain]
        src = owner.docs_global / domain
        if not src.is_dir():
            continue
        staged_domain = staged_root / domain
        _copy_domain_without_retired_bundle(src, staged_domain)
        triggers = triggers_by_publisher.setdefault(owner.slug, triggers_for_root(owner.docs_global.parent.parent))
        _write_domain_publisher_record(
            staged_domain,
            domain=domain,
            publisher=owner,
            trigger=_declared_trigger(triggers, domain=domain, publisher=owner),
        )
        copied += 1
    print(f"  Materialized docs root: {staged_root} ({copied} domain tree(s))")


def write_merged_index(publishers: list[Publisher], deploy_docs_root: Path) -> None:
    """Write the union of every publisher's global ``index.yaml`` to the root.

    One owner per domain (enforced structurally by ``domain_owners`` /
    split detection) makes a cross-owner id collision impossible, so the union is
    a plain first-wins merge — no id-collision guard. Per-domain split detection
    is the single integrity gate, and it runs before composition.
    """
    merged: list[dict[str, object]] = []  # guard: loose-dict - opaque index entries merged from external yaml
    seen_ids: set[str] = set()
    for pub in publishers:
        index_path = pub.docs_global / "index.yaml"
        if not index_path.exists():
            continue
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        snippets = payload.get("snippets")
        if not isinstance(snippets, list):
            continue
        for item in snippets:
            if not isinstance(item, dict):
                continue
            snippet_id = item.get("id")
            if not isinstance(snippet_id, str) or snippet_id in seen_ids:
                continue
            seen_ids.add(snippet_id)
            merged.append(cast("dict[str, object]", item))  # guard: loose-dict - opaque external index entry
    merged.sort(key=lambda entry: str(entry.get("id", "")))
    out = {"project_root": "~/.teleclaude", "snippets_root": "~/.teleclaude/docs", "snippets": merged}
    (deploy_docs_root / "index.yaml").write_text(
        yaml.safe_dump(out, sort_keys=False, width=1000, allow_unicode=True), encoding="utf-8"
    )
    print(f"  Merged docs index: {deploy_docs_root / 'index.yaml'} ({len(merged)} snippet(s))")


def generate_domain_baselines(
    owner_by_domain: dict[str, Publisher],
    staged_root: Path,
    project_root: Path,
    observation: DistributionObservation | None = None,
) -> None:
    """Write each owned domain's baseline bundle into the staged generation."""
    header_template = "# {name} — Platform Baseline\n\n"
    entries_by_id = _load_index_entries(staged_root / "index.yaml")
    failures: list[tuple[str, str]] = []
    for domain in sorted(owner_by_domain):
        domain_src = staged_root / domain
        baseline_src = domain_src / "baseline.md"
        if not baseline_src.exists():
            continue
        try:
            inflated = _inflate_domain_baseline(
                baseline_src, domain_src, project_root=project_root, entries_by_id=entries_by_id
            )
        except Exception as e:
            failures.append((domain, str(e)))
            continue
        bundle_dst = domain_src / GENERATED_DOMAIN_BUNDLE_FILENAME
        bundle_dst.parent.mkdir(parents=True, exist_ok=True)
        bundle_dst.write_text(header_template.format(name=domain) + inflated, encoding="utf-8")
        if observation is not None:
            logger.info(
                _DOMAIN_BASELINE_BUNDLE_GENERATED,
                process_correlation_id=observation.process_correlation_id,
                domain=domain,
            )
        print(f"  Generated domain bundle: {bundle_dst}")
    if failures:
        lines = ["", "=" * 80, "ERROR: Domain baseline bundle generation failed", "=" * 80, ""]
        lines.extend(f"{domain}: {error}" for domain, error in failures)
        lines.append("=" * 80)
        raise SystemExit("\n".join(lines))


def materialize_global_snippets(mother: Publisher | None, staged_root: Path) -> None:
    """Copy Mother-owned support fragments into the staged generation."""
    if mother is None:
        return
    source = mother.docs_global / "snippets"
    if source.is_dir():
        shutil.copytree(source, staged_root / "snippets", symlinks=False)


def materialize_global_third_party(mother: Publisher | None, staged_root: Path, deployed_root: Path) -> None:
    """Replace the staged generation's Mother-owned ``third-party/`` root with the mother's committed set.

    The root holds every global third-party document and its index. The index names
    the root's address in ``deployed_root``, where the staged generation is exchanged
    into place, so readers resolve the entries from the deployed documentation.
    A mother without a third-party set leaves the generation without the root.
    """
    if mother is None:
        return
    staged = staged_root / _THIRD_PARTY_TREE_NAME
    if staged.is_dir():
        shutil.rmtree(staged)
    source = mother.docs_global.parent / _THIRD_PARTY_TREE_NAME
    if not source.is_dir():
        return
    shutil.copytree(source, staged, symlinks=False)
    write_third_party_index_yaml(
        staged, scope=SnippetScope.GLOBAL.value, published_root=deployed_root / _THIRD_PARTY_TREE_NAME
    )


def index_entry_sort_key(entry: object) -> str:
    """Return a stable identifier key for either a decoded row or opaque entry."""
    if not isinstance(entry, Mapping):
        return _EMPTY_STRING
    snippet_id = entry.get(_INDEX_ID_KEY)
    return snippet_id if isinstance(snippet_id, str) else _EMPTY_STRING


def _resolve_domain_triggers(project_root: Path) -> dict[str, str]:
    """Merge every registered publisher's domain → activation-trigger declarations.

    Reads validated ``business.publishes`` entries directly from each
    publisher's ``teleclaude.yml`` at render time — independent of doc
    deployment (mirrors :func:`gather_publishers`'s root enumeration), so both
    render sites and no-deploy runs see the current publisher configuration
    with no dependency on a previously-deployed artifact.
    """
    triggers: dict[str, str] = dict(triggers_for_root(project_root))
    seen = {project_root.resolve(), git_common_root(project_root).resolve()}
    for root in load_roots():
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        triggers.update(triggers_for_root(root))
    return triggers


def _resolve_deployed_domain_triggers() -> dict[str, str]:
    """Read each domain's trigger from its publisher record in the activated generation.

    The record travels with the domain's published bodies, so the trigger is
    the one its publisher declared in the published revision — never a live
    declaration and never a snippet's own ``activation_trigger``.
    """
    return {domain: record.trigger for domain, record in _read_domain_publisher_records(GLOBAL_DOCS_DIR).items()}


def _inlined_bundle_domains(master_text: str, *, domains: set[str]) -> set[str]:
    """Return the domains whose generated bundle a master inlines as a Required read."""
    required_refs, _ = extract_required_reads(master_text)
    inlined: set[str] = set()
    for ref in normalize_required_refs(required_refs):
        domain = generated_domain_bundle_domain(f"{_INLINE_REF_PREFIX}{ref}", domains=domains)
        if domain is not None:
            inlined.add(domain)
    return inlined


def _render_domain_awareness(deploy_docs_root: Path, *, triggers: Mapping[str, str], inlined: set[str]) -> str:
    """Render one awareness line per published domain the global configuration does not inline.

    The listed domains are the recorded ones plus those carrying live
    global-scope entries, minus ``inlined``. Each line names the domain, its
    live global-scope snippet count (zero allowed), its bundle path, and the
    trigger its publisher recorded, so the global agent configuration surfaces
    every published domain with on-demand depth and an always-on tripwire.
    Person, company and project entries are excluded by their recorded scope.
    """
    counts: dict[str, int] = dict.fromkeys(triggers, 0)
    for entry in _live_global_entries(deploy_docs_root):
        domain = entry.get(_INDEX_DOMAIN_KEY)
        if isinstance(domain, str) and domain:
            counts[domain] = counts.get(domain, 0) + 1
    listed = sorted(domain for domain in counts if domain not in inlined)
    if not listed:
        return ""
    lines: list[str] = []
    for domain in listed:
        trigger = triggers.get(domain)
        if trigger is None:
            raise ValueError(f"Published domain '{domain}' has no discoverable activation trigger")
        lines.append(
            f"- `{domain}` — {counts[domain]} snippet(s); "
            f"bundle: `~/.teleclaude/docs/{domain}/{GENERATED_DOMAIN_BUNDLE_FILENAME}` — {trigger}"
        )
    header = "## Published Domains — load the relevant domain's bundle when needed\n\n"
    return header + "\n".join(lines)


def deploy_documentation(
    project_root: Path,
    docs_source_dir: Path,
    *,
    deploy_docs_root: Path | None = None,
    observation: DistributionObservation | None = None,
    committed_owner: bool = False,
    preserve_previous: bool = False,
) -> Path | None:
    """The documentation deployment step: publish one complete docs generation.

    Gathers every contributing publisher (the current project contributes from
    ``docs_source_dir``, its live checkout, so a worktree's edits compose),
    resolves the one owner per domain — hard-blocking on a split before any
    publication — then materializes domains, support fragments, indexes, and
    baseline bundles beside the deployed root. The completed staging generation
    exchanges with the live root atomically; callers may retain the displaced
    generation until their build finishes.
    """
    if not docs_source_dir.is_dir():
        return None
    target = deploy_docs_root if deploy_docs_root is not None else GLOBAL_DOCS_DIR
    print("\nDeploying documentation...")
    publishers = gather_publishers(project_root, docs_source_dir.resolve())
    try:
        with publisher_resolution(project_root, publishers=publishers) as registry:
            owner_by_domain = registry.owners
            mother = registry.mother
            target.parent.mkdir(parents=True, exist_ok=True)
            staged_root = Path(tempfile.mkdtemp(prefix=".docs.next-", dir=target.parent))
            try:
                if committed_owner:
                    current = next(
                        publisher
                        for publisher in publishers
                        if publisher.docs_global.resolve() == docs_source_dir.resolve()
                    )
                    _materialize_committed_owner(
                        current,
                        owner_by_domain,
                        staged_root,
                        target,
                        project_root,
                        observation,
                        mother=mother,
                    )
                    if mother is not None and mother.slug == current.slug:
                        # Only the mother's publication renders the domain roster,
                        # so only it requires every published domain's record.
                        _require_domain_publisher_records(staged_root)
                else:
                    materialize_docs_root(owner_by_domain, staged_root)
                    materialize_global_snippets(mother, staged_root)
                    materialize_global_third_party(mother, staged_root, target)
                    write_merged_index(publishers, staged_root)
                    generate_domain_baselines(owner_by_domain, staged_root, project_root, observation)
                previous_root = publish_generation(staged_root, target)
            except Exception:
                shutil.rmtree(staged_root, ignore_errors=True)
                raise
    except DocsPublisherResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if previous_root is not None and not preserve_previous:
        if previous_root.is_symlink():
            previous_root.unlink()
        else:
            shutil.rmtree(previous_root)
    return previous_root


def _materialize_committed_owner(
    current: Publisher,
    owner_by_domain: dict[str, Publisher],
    staged_root: Path,
    deployed_root: Path,
    project_root: Path,
    observation: DistributionObservation | None,
    *,
    mother: Publisher | None,
) -> None:
    """Replace one publisher's deployed contributions inside a copied generation.

    The publisher's domains are its old index rows, its current declaration and
    every staged domain whose publisher record names it, so a domain it stopped
    declaring leaves with its record even when it had no snippets. Each domain
    it still owns is re-copied from the snapshot beside a fresh record carrying
    the trigger the snapshot declares.
    """
    if deployed_root.is_dir():
        shutil.copytree(deployed_root, staged_root, dirs_exist_ok=True, symlinks=False)
    deployed_index = deployed_root / INDEX_FILE_NAME
    existing_payload = yaml.safe_load(deployed_index.read_text(encoding=UTF8)) if deployed_index.is_file() else {}
    existing_entries = existing_payload.get(INDEX_SNIPPETS_KEY, []) if isinstance(existing_payload, dict) else []
    if not isinstance(existing_entries, list):
        existing_entries = []
    retained: list[object] = [
        entry
        for entry in existing_entries
        if not isinstance(entry, dict) or entry.get(SOURCE_PROJECT_KEY) != current.slug
    ]
    owned_domains: set[str] = set()
    for entry in existing_entries:
        if not isinstance(entry, dict) or entry.get(SOURCE_PROJECT_KEY) != current.slug:
            continue
        domain = entry.get(_INDEX_DOMAIN_KEY)
        if isinstance(domain, str):
            owned_domains.add(domain)
    owned_domains.update(current.publishes)
    owned_domains.update(
        domain
        for domain, record in _read_domain_publisher_records(staged_root).items()
        if record.publisher == current.slug
    )
    declared_triggers = triggers_for_root(project_root)
    for domain in sorted(owned_domains):
        staged_domain = staged_root / domain
        if staged_domain.is_dir():
            shutil.rmtree(staged_domain)
        source_domain = current.docs_global / domain
        if domain in owner_by_domain and owner_by_domain[domain].slug == current.slug and source_domain.is_dir():
            _copy_domain_without_retired_bundle(source_domain, staged_domain)
            _write_domain_publisher_record(
                staged_domain,
                domain=domain,
                publisher=current,
                trigger=_declared_trigger(declared_triggers, domain=domain, publisher=current),
            )
    _retire_carried_over_bundles(staged_root, owned_domains=owned_domains)
    if mother is not None and mother.slug == current.slug:
        staged_snippets = staged_root / _SNIPPETS_TREE_PATH
        if staged_snippets.is_dir():
            shutil.rmtree(staged_snippets)
        source_snippets = current.docs_global / _SNIPPETS_TREE_PATH
        if source_snippets.is_dir():
            shutil.copytree(source_snippets, staged_snippets, symlinks=False)
        materialize_global_third_party(current, staged_root, deployed_root)
    source_index = current.docs_global / INDEX_FILE_NAME
    source_payload = yaml.safe_load(source_index.read_text(encoding=UTF8)) if source_index.is_file() else {}
    source_entries = source_payload.get(INDEX_SNIPPETS_KEY, []) if isinstance(source_payload, dict) else []
    if not isinstance(source_entries, list):
        source_entries = []
    retained_ids = {
        entry.get(_INDEX_ID_KEY)
        for entry in retained
        if isinstance(entry, dict) and isinstance(entry.get(_INDEX_ID_KEY), str)
    }
    incoming: list[SnippetIndexEntry] = [
        cast(SnippetIndexEntry, entry) for entry in source_entries if isinstance(entry, dict)
    ]
    for entry in incoming:
        snippet_id = entry.get(_INDEX_ID_KEY)
        if isinstance(snippet_id, str) and snippet_id in retained_ids:
            raise DocsPublisherResolutionError(_COMMITTED_OWNER_COLLISION.format(snippet_id=snippet_id))
    merged_entries: list[object] = [*retained, *incoming]
    merged_entries.sort(key=index_entry_sort_key)
    (staged_root / INDEX_FILE_NAME).write_text(
        yaml.safe_dump(
            {
                INDEX_PROJECT_ROOT_KEY: INDEX_SCOPE_ROOT,
                INDEX_SNIPPETS_ROOT_KEY: INDEX_DEPLOY_ROOT,
                INDEX_SNIPPETS_KEY: merged_entries,
            },
            sort_keys=False,
            width=1000,
            allow_unicode=True,
        ),
        encoding=UTF8,
    )
    current_domains = {
        domain: publisher for domain, publisher in owner_by_domain.items() if publisher.slug == current.slug
    }
    generate_domain_baselines(current_domains, staged_root, project_root, observation)


def _strip_specific_h1(content: str, title: str) -> str:
    """Remove a specific leading H1 heading to avoid redundant titles in inlined docs."""
    lines = content.splitlines()
    if not lines:
        return content
    if lines[0].strip() == f"# {title}":
        return "\n".join(lines[1:]).lstrip("\n")
    return content


def _strip_leading_separators(content: str) -> str:
    """Remove leading markdown separators to avoid stacked '---' blocks."""
    lines = content.splitlines()
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "---":
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
    return "\n".join(lines[idx:]).lstrip("\n")


def _iter_project_agent_masters(project_root: Path) -> list[Path]:
    """Find AGENTS.master.md files in the project (excluding tool-managed dirs)."""
    skip_dirs = {
        ".git",
        ".agents",
        ".history",
        "trees",
        "__pycache__",
        "dist",
        "node_modules",
        ".venv",
        "venv",
    }
    # Skill package directories can carry arbitrary, deep third-party file
    # trees, including a coincidentally named AGENTS.master.md that is not a
    # project-directory master. Every root this repository's own skill tree
    # can occupy — tiered and project-local — is skipped
    # rather than walked; global_skill_source_root is a plain path join that
    # also resolves in a side project.
    # TeleClaude's template trees hold masters that are templates, not
    # project-directory masters; they are excluded by location, and only
    # where the project is Mother.
    skill_tree_roots = {
        global_skill_source_root(project_root),
        agent_artifacts.project_skills_root(project_root),
    }
    if agent_artifacts.is_mother_project(project_root):
        skill_tree_roots.add(template_tree_root(project_root))
    matches: list[Path] = []
    for root, dirs, files in os.walk(project_root):
        root_path = Path(root)
        if root_path in skill_tree_roots:
            dirs.clear()
            continue
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        if PROJECT_MASTER_FILENAME in files:
            matches.append(root_path / PROJECT_MASTER_FILENAME)
    return sorted(matches)


def _strip_lock_sentinels(content: str) -> str:
    """Drop the master file's authoring lock sentinels from generated output.

    The lock addresses whoever opens a master file to edit it; a generated
    entrypoint is never edited, so the sentinel is noise in an agent's context.
    """
    stripped = LOCK_SENTINEL_RE.sub("", content)
    collapsed = re.sub(r"\n{3,}", "\n\n", stripped).strip("\n")
    return f"{collapsed}\n" if collapsed else ""


def _code_span_ranges(source: str) -> list[tuple[int, int]]:
    """Locate code spans in raw inline source by CommonMark's backtick-run rule.

    A run of N backticks opens a span closed by the next run of exactly N; an
    unmatched run is literal, and a backslash outside a span escapes the next
    character.
    """
    ranges: list[tuple[int, int]] = []
    index = 0
    length = len(source)
    while index < length:
        if source[index] == _BACKSLASH:
            index += 2
            continue
        if source[index] != _BACKTICK:
            index += 1
            continue
        run_end = index
        while run_end < length and source[run_end] == _BACKTICK:
            run_end += 1
        run = run_end - index
        cursor = run_end
        closing = -1
        while cursor < length:
            if source[cursor] != _BACKTICK:
                cursor += 1
                continue
            closing_end = cursor
            while closing_end < length and source[closing_end] == _BACKTICK:
                closing_end += 1
            if closing_end - cursor == run:
                closing = cursor
                break
            cursor = closing_end
        if closing < 0:
            index = run_end
            continue
        ranges.append((index, closing + run))
        index = closing + run
    return ranges


def _code_span_content(span: str, run: int) -> str:
    """Normalize a code span's content the way CommonMark does, for comparison with the lexer."""
    content = span[run:-run].replace(_NEWLINE, _SPACE)
    if len(content) >= 2 and content.startswith(_SPACE) and content.endswith(_SPACE) and content.strip(_SPACE):
        return content[1:-1]
    return content


def _mask_code_spans(inline: Token) -> str:
    """Return an inline run's raw source with its code spans masked.

    The spans found in the source must match the lexer's own code spans, at any
    nesting depth, one for one; otherwise nothing is masked, so a disagreement
    fails closed.
    """
    source = inline.content
    ranges = _code_span_ranges(source)
    found = [_code_span_content(source[start:end], _run_length(source, start)) for start, end in ranges]
    lexed = [token.content for token in _descendants(inline) if token.type == _INLINE_CODE_TOKEN_TYPE]
    if found != lexed:
        return source
    masked = source
    for start, end in reversed(ranges):
        masked = masked[:start] + _MASK * (end - start) + masked[end:]
    return masked


def _descendants(token: Token) -> list[Token]:
    """Return every token nested under ``token`` in source order (image alt text holds its own children)."""
    found: list[Token] = []
    for child in token.children or []:
        found.append(child)
        found.extend(_descendants(child))
    return found


def _run_length(source: str, start: int) -> int:
    end = start
    while end < len(source) and source[end] == _BACKTICK:
        end += 1
    return end - start


def runtime_imports(text: str) -> list[str]:
    """Return every import token the agent runtime would load from ``text``.

    Follows the runtime's grammar (``third-party/claude-code/instruction-files``):
    only Markdown fenced code blocks and code spans are excluded. A CommonMark
    lexer locates them — fences by line range, code spans within each inline
    run's raw source — and every other line of the raw source is scanned as
    written: alt text, link titles, reference definitions, HTML and indented
    code included.
    """
    lines = text.split(_NEWLINE)
    covered: set[int] = set()
    scanned: list[str] = []
    for token in _MARKDOWN_LEXER.parse(text):
        if token.map is None:
            continue
        if token.type == _FENCE_TOKEN_TYPE:
            covered.update(range(*token.map))
        elif token.type == _INLINE_TOKEN_TYPE:
            covered.update(range(*token.map))
            scanned.append(_mask_code_spans(token))
    scanned.extend(line for number, line in enumerate(lines) if number not in covered)
    return [match.group(0) for block in scanned for match in _RUNTIME_IMPORT_RE.finditer(block)]


def assert_self_contained(text: str, *, entrypoint: Path) -> None:
    """Fail when a generated entrypoint's final text would still import a file at runtime."""
    tokens = runtime_imports(text)
    if tokens:
        raise UnresolvedImportError(entrypoint, tokens)


def inflate_master(
    master_path: Path,
    *,
    project_root: Path,
    root_extras: bool,
    warn_only: bool,
    observation: DistributionObservation | None,
    resolution: DocsResolutionMode = DocsResolutionMode.SOURCE,
) -> str:
    """Compile one ``AGENTS.master.md`` into the fully inlined text of its ``AGENTS.md``.

    Required reads expand under ``resolution``: a publisher's source tree, or
    the deployed corpus. Only a root master (``root_extras``) gains the
    progressive sibling sections and the project MCP index; the lock sentinels
    never reach the output. Raises an ``EntrypointCompositionError`` when a
    required read does not resolve or the result still carries an import.
    """
    resolution_scope = (
        publisher_resolution(project_root) if resolution is DocsResolutionMode.SOURCE else deployed_resolution()
    )
    with resolution_scope:
        raw = master_path.read_text(encoding=UTF8)
        inflated = expand_inline_refs(
            raw,
            project_root=project_root,
            current_path=master_path,
            warn_only=warn_only,
            observation=observation,
        )
        if root_extras:
            sections = _progressive_sibling_sections(
                project_root / _PROJECT_DOCS_RELATIVE_PATH,
                scope=ProjectScope(),
                project_root=project_root,
                warn_only=warn_only,
            )
            if sections:
                inflated = _APPENDED_SECTION_TEMPLATE.format(content=inflated.rstrip(), sections=sections)
            canonical_project_root = project_mcp_root(project_root)
            if canonical_project_root is not None:
                project_index = _render_mcp_index(load_project_declarations(canonical_project_root))
                if project_index:
                    inflated = _APPENDED_SECTION_TEMPLATE.format(content=inflated.rstrip(), sections=project_index)
    composed = _strip_lock_sentinels(inflated)
    assert_self_contained(composed, entrypoint=master_path)
    return composed


def _inflate_project_master(
    master_path: Path,
    *,
    project_root: Path,
    warn_only: bool,
    observation: DistributionObservation | None,
) -> str:
    """Compile one project master; only the project's root master gains the root extras."""
    return inflate_master(
        master_path,
        project_root=project_root,
        root_extras=master_path == project_root / PROJECT_MASTER_FILENAME,
        warn_only=warn_only,
        observation=observation,
    )


def _write_project_agents(
    master_path: Path,
    *,
    project_root: Path,
    warn_only: bool,
    observation: DistributionObservation | None,
) -> Path:
    """Generate the ``AGENTS.md`` next to a project ``AGENTS.master.md``, the only file written there."""
    inflated = _inflate_project_master(
        master_path,
        project_root=project_root,
        warn_only=warn_only,
        observation=observation,
    )
    agents_path = master_path.parent / GENERATED_ENTRYPOINT_FILENAME
    agents_path.write_text(inflated, encoding=UTF8)
    return agents_path


def _render_global_skill_catalog(
    catalog_master: Path,
    *,
    mother_root: Path,
    warn_only: bool,
    observation: DistributionObservation | None,
) -> str:
    """Render the Mother-owned catalog through the normal inline directive pipeline."""
    return inflate_master(
        catalog_master,
        project_root=mother_root,
        root_extras=False,
        warn_only=warn_only,
        observation=observation,
    )


def _resolve_pipeline_capabilities(
    *, deploy: bool, agents_enabled: bool | None, docs_enabled: bool | None, project_root: Path
) -> tuple[bool, bool]:
    """Resolve omitted deploy flags from the project declaration."""
    if not deploy:
        return True, True
    resolved = resolve_capabilities(project_root) if agents_enabled is None or docs_enabled is None else None
    effective_agents = agents_enabled if agents_enabled is not None else bool(resolved and resolved.agents)
    effective_docs = docs_enabled if docs_enabled is not None else bool(resolved and resolved.docs)
    return effective_agents, effective_docs


def main(  # noqa: C901 - coordinates the distribution phases at one entry point.
    request: DistributionRequest | None = None, *, build_state: DistributionBuildState | None = None
) -> DistributionResult | DistributionBuild:
    """Build agent artifacts for supported CLIs; deployment requires an internal request."""
    if request is None:
        parser = argparse.ArgumentParser(description="Validate and build agent outputs into dist/.")
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
        parser.add_argument(
            _AGENTS_ENABLED_FLAG, action=argparse.BooleanOptionalAction, default=None, help=_AGENTS_ENABLED_HELP
        )
        parser.add_argument(
            _DOCS_ENABLED_FLAG, action=argparse.BooleanOptionalAction, default=None, help=_DOCS_ENABLED_HELP
        )
        args = parser.parse_args()
    else:
        args = argparse.Namespace(
            project_root=str(request.project_root),
            deploy_root=str(request.deploy_root),
            validate_only=request.validate_only,
            warn_only=request.warn_only,
            agents_enabled=request.agents_enabled,
            docs_enabled=request.docs_enabled,
        )
    deploy = request is not None and request.deploy
    committed_publication = request is not None and deploy
    publication_build = committed_publication and request.preserve_previous_documentation
    if publication_build and build_state is None:
        raise ValueError(_PUBLICATION_BUILD_STATE_REQUIRED)

    # Get the project root and main TeleClaude repo root.
    teleclaude_root = str(_REPO_ROOT)
    project_root = os.path.abspath(os.path.expanduser(args.project_root))
    deploy_root = os.path.abspath(os.path.expanduser(args.deploy_root)) if request is not None else project_root
    is_mother_project = agent_artifacts.is_mother_project(Path(project_root))
    halves = request.halves if request is not None else PublicationHalves.BOTH
    publishes_local_half = halves is not PublicationHalves.PUBLISHED
    project_root_path = Path(project_root)
    checkout_local_outputs: list[Path] = []
    retired_pointers: list[Path] = []
    staged_publication_phases: list[StagedPublicationPhase] = []
    publication_staging_roots = build_state.staging_roots if build_state is not None else []
    agents_enabled, docs_enabled = _resolve_pipeline_capabilities(
        deploy=deploy,
        agents_enabled=args.agents_enabled,
        docs_enabled=args.docs_enabled,
        project_root=project_root_path,
    )
    agents_root = os.path.join(project_root if is_mother_project and request is not None else teleclaude_root, "agents")
    project_agents_root = str(agent_artifacts.local_tier_root(project_root_path))
    os.chdir(project_root)
    canonical_root = git_common_root(project_root_path)
    master_docs_dir = os.path.join(project_root, "docs", "global")
    canonical_docs_dir = os.path.join(canonical_root, "docs", "global")
    docs_source_dir = master_docs_dir if os.path.isdir(master_docs_dir) or request is not None else canonical_docs_dir
    observation = DistributionObservation(str(uuid4())) if deploy else None

    if observation is not None:
        logger.info(
            _ARTIFACT_DISTRIBUTION_STARTED,
            process_correlation_id=observation.process_correlation_id,
        )
    if deploy and docs_enabled:
        previous_root = deploy_documentation(
            project_root_path,
            Path(docs_source_dir),
            observation=observation,
            committed_owner=request is not None,
            preserve_previous=publication_build,
        )
        if build_state is not None:
            build_state.documentation_target = GLOBAL_DOCS_DIR
            build_state.documentation_published = Path(docs_source_dir).is_dir()
            build_state.previous_documentation_root = previous_root

    # Agent rendering consumes publisher declarations to build domain awareness,
    # so resolve and validate them only when the agents pipeline is enabled.
    if not agents_enabled:
        domain_triggers = {}
    elif request is not None:
        domain_triggers = _resolve_deployed_domain_triggers()
    else:
        domain_triggers = _resolve_domain_triggers(project_root_path)

    if agents_enabled and deploy and publishes_local_half:
        for master_path in _iter_project_agent_masters(project_root_path):
            checkout_local_outputs.append(
                _write_project_agents(
                    master_path,
                    project_root=project_root_path,
                    warn_only=args.warn_only,
                    observation=observation,
                )
            )
            retired_pointers.append(retired_pointer_candidate(master_path.parent))

    validate_only = args.validate_only
    dist_dir = "dist"

    master_agents_file = os.path.join(agents_root, "AGENTS.global.md")
    project_skills_dir = str(agent_artifacts.project_skills_root(project_root_path))
    agents_config: dict[str, AgentConfig] = {
        "claude": {
            "home_root": os.path.expanduser("~/.claude"),
            "project_dir": ".claude",
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "claude", "CLAUDE.md"),
            "skills_dest_dir": os.path.join(dist_dir, "claude", "skills"),
            "skills_ext": ".md",
        },
        "codex": {
            "home_root": os.path.expanduser("~/.codex"),
            "project_dir": ".codex",
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "codex", "AGENTS.md"),
            "skills_dest_dir": os.path.join(dist_dir, "codex", "skills"),
            "skills_ext": ".md",
        },
        "gemini": {
            "home_root": os.path.expanduser("~/.gemini/antigravity-cli"),
            "project_dir": ".gemini",
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "gemini", "AGENTS.md"),
            "skills_dest_dir": os.path.join(dist_dir, "gemini", "skills"),
            "skills_ext": ".md",
        },
        "deepseek": {
            "home_root": os.path.expanduser("~/.dsh"),
            "project_dir": ".dsh",
            "prefix": "/",
            "master_dest": os.path.join(dist_dir, "deepseek", "AGENTS.md"),
            "skills_dest_dir": os.path.join(dist_dir, "deepseek", "skills"),
            "skills_ext": ".md",
        },
    }

    artifact_specs: list[FileArtifactType] = [
        FileArtifactType(
            name="skills",
            source_dir_key="skills",
            dest_dir_key="skills_dest_dir",
            ext_key="skills_ext",
            artifact_kind=ArtifactKind.SKILL,
        ),
    ]

    global_sources = []
    if is_mother_project:
        global_sources = [
            {
                "label": "agents",
                "master": master_agents_file,
            }
        ]
    local_sources = [
        {
            "label": _LOCAL_AGENTS_SOURCE_LABEL,
            "master": os.path.join(project_agents_root, "__none__"),
            "skills": project_skills_dir,
        },
    ]

    def _existing_sources(source_list: list[dict[str, str]]) -> list[dict[str, str]]:
        existing: list[dict[str, str]] = []
        for source in source_list:
            if source["label"] in {"agents", _LOCAL_AGENTS_SOURCE_LABEL}:
                existing.append(source)
                continue
            if os.path.isfile(source.get("master", "")) or os.path.isdir(source.get("skills", "")):
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
                    candidate = os.path.join(source_dir, item, "SKILL.md")
                    if os.path.exists(candidate):
                        item_path = candidate
                        break
                if not item_path:
                    continue
                try:
                    with open(item_path, encoding="utf-8") as f:
                        post = frontmatter.load(f)
                    validate_artifact(post, item_path, kind=spec.artifact_kind, project_root=Path(project_root))
                    resolve_skill_name(post, item)
                except Exception as e:
                    errors.append(str(e))
        return errors

    errors: list[str] = []
    if agents_enabled:
        if not committed_publication:
            errors.extend(_validate_sources(global_sources))
            errors.extend(_validate_sources(local_sources))
    if errors:
        for error in errors:
            print(error)
        if not args.warn_only:
            raise SystemExit(1)
    if validate_only:
        return DistributionResult(tuple(checkout_local_outputs), tuple(retired_pointers))

    dist_dir = "dist"
    if agents_enabled:
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)
        os.makedirs(dist_dir)

    def _run_phase_cached(  # noqa: C901
        *,
        sources: list[dict[str, str]],
        prefix_root: str,
        dist_dir: str,
        deploy_root: str,
        emit_repo_codex: bool,
        deploy_enabled: bool,
        is_global_phase: bool,
        scope_key: str,
    ) -> None:
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)
        os.makedirs(dist_dir)

        agent_master_contents: list[str] = []
        artifact_items: dict[str, list[str]] = {spec.name: [] for spec in artifact_specs}
        for source in sources:
            if os.path.isfile(source["master"]) and source["label"] != _LOCAL_AGENTS_SOURCE_LABEL:
                with open(source["master"], encoding="utf-8") as f:
                    agent_master_contents.append(f.read())
            for spec in artifact_specs:
                source_dir = source.get(spec.source_dir_key)
                if not isinstance(source_dir, str) or not os.path.isdir(source_dir):
                    continue
                artifact_items[spec.name].extend(
                    [name for name in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, name))]
                )
        for spec in artifact_specs:
            artifact_items[spec.name] = sorted(set(artifact_items[spec.name]))

        # Commands are not an artifact kind: the staged corpus is empty, so deployment retracts every
        # command file this repository owned in the manifest.
        commands_dist_dir = Path(dist_dir) / _COMMANDS_STAGING_DIRECTORY
        commands_dist_dir.mkdir(parents=True, exist_ok=True)

        built_agents: list[str] = []
        for agent_name, config in agents_config.items():
            if agent_name != "agents" and not os.path.isdir(config["home_root"]):
                print(f"Skipping {agent_name}: directory {config['home_root']} not found.")
                continue

            print(f"Processing {agent_name}...")

            agent_specific_file = os.path.join(prefix_root, f"{agent_name.upper()}.addendum.md")
            agent_specific_content = ""
            if os.path.exists(agent_specific_file):
                with open(agent_specific_file, encoding="utf-8") as extra_f:
                    raw_agent_specific = extra_f.read()
                agent_specific_content = process_file(raw_agent_specific, config["prefix"], agent_name)

            has_any_content = bool(
                agent_master_contents
                or any(artifact_items[spec.name] for spec in artifact_specs)
                or agent_specific_content
            )
            if not has_any_content:
                print(f"Skipping {agent_name}: no agent content found.")
                continue

            master_dest_path = os.path.join(dist_dir, agent_name, os.path.basename(config["master_dest"]))
            processed_contents = [
                process_file(content, config["prefix"], agent_name) for content in agent_master_contents
            ]
            addendum_suffix = f"\n---\n\n{agent_specific_content}" if agent_specific_content else ""
            combined_agents_content = "\n\n".join(content for content in (*processed_contents,) if content)
            if _should_expand_inline(agent_name) and processed_contents:
                expanded_body = expand_inline_refs(
                    "\n\n".join(content for content in processed_contents if content),
                    project_root=Path(project_root),
                    current_path=Path(project_root) / "AGENTS.md",
                    warn_only=args.warn_only,
                    observation=observation,
                )
                combined_agents_content = expanded_body
            if combined_agents_content:
                combined_agents_content = combined_agents_content.rstrip() + addendum_suffix
                if is_global_phase:
                    inlined = _inlined_bundle_domains(
                        "\n\n".join(content for content in processed_contents if content),
                        domains=load_domains(Path(project_root)),
                    )
                    awareness = _render_domain_awareness(GLOBAL_DOCS_DIR, triggers=domain_triggers, inlined=inlined)
                    if awareness:
                        combined_agents_content = f"{combined_agents_content.rstrip()}\n\n---\n\n{awareness}\n"
                combined_agents_content = _strip_lock_sentinels(combined_agents_content)
                assert_self_contained(combined_agents_content, entrypoint=Path(master_dest_path))
            if combined_agents_content:
                master_dest_dir = os.path.dirname(master_dest_path)
                if master_dest_dir:
                    os.makedirs(master_dest_dir, exist_ok=True)
                with open(master_dest_path, "w", encoding="utf-8") as f:
                    f.write(combined_agents_content)
                if emit_repo_codex and agent_name == "codex":
                    repo_override_path = os.path.join(project_root, "AGENTS.override.md")
                    with open(repo_override_path, "w", encoding="utf-8") as f:
                        f.write(combined_agents_content)
                    checkout_local_outputs.append(Path(repo_override_path))

            for spec in artifact_specs:
                items = artifact_items[spec.name]
                if not items:
                    continue
                dest_dir = os.path.join(
                    dist_dir,
                    agent_name,
                    os.path.basename(config[spec.dest_dir_key]),  # type: ignore[literal-required]
                )
                os.makedirs(dest_dir, exist_ok=True)
                for item in items:
                    item_path = ""
                    for source in sources:
                        source_dir = source.get(spec.source_dir_key)
                        if not isinstance(source_dir, str):
                            continue
                        candidate = os.path.join(source_dir, item, "SKILL.md")
                        if os.path.exists(candidate):
                            item_path = candidate
                            break
                    if not item_path:
                        continue
                    with open(item_path, encoding="utf-8") as f:
                        try:
                            post = frontmatter.load(f)
                            if not committed_publication:
                                validate_artifact(
                                    post,
                                    item_path,
                                    kind=spec.artifact_kind,
                                    project_root=Path(project_root),
                                )
                            prepared = _prepare_post(
                                post,
                                agent_prefix=config["prefix"],
                                agent_name=agent_name,
                                project_root=Path(project_root),
                                current_path=Path(item_path),
                                warn_only=args.warn_only,
                                observation=observation,
                            )
                            skill_name = resolve_skill_name(prepared, item)
                            if agent_name == "claude":
                                transformed_content = transform_skill_to_claude(prepared, skill_name)
                            elif agent_name == "codex":
                                transformed_content = transform_skill_to_codex(prepared, skill_name)
                            elif agent_name == "deepseek":
                                transformed_content = transform_skill_to_deepseek(prepared, skill_name)
                            else:
                                transformed_content = transform_skill_to_gemini(prepared, skill_name)
                            output_dir = os.path.join(dest_dir, item)
                            os.makedirs(output_dir, exist_ok=True)
                            output_filename = f"SKILL{config[spec.ext_key]}"  # type: ignore[literal-required]
                            output_path = os.path.join(output_dir, output_filename)
                            with open(output_path, "w", encoding="utf-8") as out_f:
                                out_f.write(transformed_content.rstrip("\n") + "\n")
                            # Copy supporting files/dirs from skill source (everything except SKILL.md)
                            if output_dir:
                                skill_source_dir = os.path.dirname(item_path)
                                for entry in os.listdir(skill_source_dir):
                                    if entry == "SKILL.md" or entry.startswith((".", "__")):
                                        continue
                                    src_entry = os.path.join(skill_source_dir, entry)
                                    dst_entry = os.path.join(output_dir, entry)
                                    if os.path.isdir(src_entry):
                                        if os.path.exists(dst_entry):
                                            shutil.rmtree(dst_entry)
                                        shutil.copytree(src_entry, dst_entry)
                                    else:
                                        shutil.copy2(src_entry, dst_entry)
                        except Exception as e:
                            message = _ARTIFACT_PROCESSING_ERROR.format(
                                kind=spec.name,
                                item=item,
                                agent=agent_name,
                                error=e,
                            )
                            raise RuntimeError(message) from e

            built_agents.append(agent_name)

        print("\nTranspilation complete.")

        if deploy and deploy_enabled:
            if publication_build:
                staged_publication_phases.append(
                    StagedPublicationPhase(
                        dist_dir=Path(dist_dir),
                        built_agents=tuple(built_agents),
                        deploy_root=deploy_root,
                        is_global_phase=is_global_phase,
                        scope_key=scope_key,
                        commands_dist_dir=commands_dist_dir,
                    )
                )
            else:
                print("Deploying files...")
                for agent_name in built_agents:
                    config = agents_config[agent_name]

                    print(f"Deploying {agent_name}...")

                    target_root = (
                        config["home_root"] if is_global_phase else os.path.join(deploy_root, config["project_dir"])
                    )
                    dist_agent_root = os.path.join(dist_dir, agent_name)
                    _deploy_agent(
                        dist_agent_root=dist_agent_root,
                        target_root=target_root,
                    )

                # Only the global phase stages commands. Its scope key is the publishing checkout's
                # canonical root, which the project-local phase of that same checkout shares, so a
                # local-phase reconcile would retract the corpus the global phase just deployed.
                if is_global_phase:
                    shutil.copytree(commands_dist_dir, COMMANDS_DIR, dirs_exist_ok=True)
                    reconcile_deployed_files(scope_key=scope_key, staged_commands_dir=commands_dist_dir)
                retract_retired_native_artifacts(
                    scope_key=scope_key,
                    scope_root=Path(deploy_root),
                    is_global_scope=is_global_phase,
                    replacement_master_written=(
                        Path(dist_dir)
                        / _GEMINI_AGENT_NAME
                        / os.path.basename(agents_config[_GEMINI_AGENT_NAME]["master_dest"])
                    ).is_file(),
                )

                print("Deployment complete.")

    def _run_phase(
        *,
        sources: list[dict[str, str]],
        prefix_root: str,
        dist_dir: str,
        deploy_root: str,
        emit_repo_codex: bool,
        deploy_enabled: bool,
        is_global_phase: bool,
        scope_key: str,
    ) -> None:
        with publisher_resolution(project_root_path):
            _run_phase_cached(
                sources=sources,
                prefix_root=prefix_root,
                dist_dir=dist_dir,
                deploy_root=deploy_root,
                emit_repo_codex=emit_repo_codex,
                deploy_enabled=deploy_enabled,
                is_global_phase=is_global_phase,
                scope_key=scope_key,
            )

    if deploy and is_mother_project:
        checkout_local_outputs.extend(
            compose_global_skill_catalog(
                project_root_path,
                partial(
                    _render_global_skill_catalog,
                    mother_root=project_root_path,
                    warn_only=args.warn_only,
                    observation=observation,
                ),
            ),
        )
        retired_pointers.append(retired_pointer_candidate(global_skill_source_root(project_root_path)))
        if agents_enabled:
            global_dist_context: AbstractContextManager[str]
            if publication_build:
                global_dist = tempfile.mkdtemp(prefix=_GLOBAL_DISTRIBUTION_TEMP_PREFIX)
                publication_staging_roots.append(Path(global_dist))
                global_dist_context = nullcontext(global_dist)
            else:
                global_dist_context = tempfile.TemporaryDirectory(prefix=_GLOBAL_DISTRIBUTION_TEMP_PREFIX)
            with global_dist_context as global_dist:
                if global_sources:
                    _run_phase(
                        sources=global_sources,
                        prefix_root=agents_root,
                        dist_dir=global_dist,
                        deploy_root=os.path.expanduser("~"),
                        emit_repo_codex=False,
                        deploy_enabled=True,
                        is_global_phase=True,
                        scope_key=platform_scope_key(),
                    )
            local_dist_context: AbstractContextManager[str]
            if publication_build:
                local_dist = tempfile.mkdtemp(prefix=_LOCAL_DISTRIBUTION_TEMP_PREFIX)
                publication_staging_roots.append(Path(local_dist))
                local_dist_context = nullcontext(local_dist)
            else:
                local_dist_context = tempfile.TemporaryDirectory(prefix=_LOCAL_DISTRIBUTION_TEMP_PREFIX)
            with local_dist_context as local_dist:
                if local_sources and publishes_local_half:
                    _run_phase(
                        sources=local_sources,
                        prefix_root=project_agents_root,
                        dist_dir=local_dist,
                        deploy_root=deploy_root,
                        emit_repo_codex=True,
                        deploy_enabled=True,
                        is_global_phase=False,
                        scope_key=str(canonical_root.resolve()),
                    )
        if observation is not None:
            logger.info(
                _ARTIFACT_DISTRIBUTION_COMPLETED,
                process_correlation_id=observation.process_correlation_id,
            )
    else:
        if global_sources:
            _run_phase(
                sources=global_sources,
                prefix_root=agents_root,
                dist_dir=os.path.join(project_root, "dist", "global"),
                deploy_root=os.path.expanduser("~"),
                emit_repo_codex=False,
                deploy_enabled=False,
                is_global_phase=True,
                scope_key=str(canonical_root.resolve()),
            )

        if local_sources:
            _run_phase(
                sources=local_sources,
                prefix_root=project_agents_root,
                dist_dir=os.path.join(project_root, "dist", "local"),
                deploy_root=project_root,
                emit_repo_codex=deploy,
                deploy_enabled=False,
                is_global_phase=False,
                scope_key=project_root,
            )

    result = DistributionResult(tuple(checkout_local_outputs), tuple(retired_pointers))
    if publication_build and build_state is not None:
        return DistributionBuild(
            result=result,
            phases=tuple(staged_publication_phases),
            agents_config=agents_config,
            state=build_state,
        )
    return result


if __name__ == "__main__":
    main()
