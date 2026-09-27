"""Project setup orchestration flow."""

from __future__ import annotations

import io
import os
import shutil
from pathlib import Path

from instrukt_ai_logging import get_logger
from ruamel.yaml import YAML

from teleclaude.capabilities import Capabilities, CapabilityName, resolve_capabilities
from teleclaude.config import config
from teleclaude.config._file_io import file_transaction
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.declaration import render_declared_config
from teleclaude.config.machine_config_mutation import add_trusted_directory
from teleclaude.config.migrations import Destination, MigrationTrigger, carry_pending, migrate_document, upcast
from teleclaude.config.migrations._registry import registered_subject
from teleclaude.config.schema import ConfigKind, ProjectConfig
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.reconciliation.template_installation import materialize_template_tree
from teleclaude.docs_index import ensure_project_config, get_project_slug
from teleclaude.git import Repo
from teleclaude.paths import ConfigFileName
from teleclaude.project_manifest import register_root
from teleclaude.project_root import resolve_project_root
from teleclaude.project_setup.domain_seeds import seed_event_domains
from teleclaude.project_setup.git_repo import ensure_git_repo
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.skeleton import deploy_skeleton
from teleclaude.quality.scope import get_project_languages
from teleclaude.slug import normalize_slug, validate_slug
from teleclaude.utils import resolve_project_config_path

logger = get_logger(__name__)

_DOCS_DIRECTORY = "docs"
# `.agents/` is deliberately excluded: it is the local phase's delivery
# location, never an authored source, so its presence must never turn the
# `agents` capability on. See `teleclaude.agent_artifacts`.
_AGENT_DIRECTORIES = ("agents",)
_MAKEFILE_NAME = "Makefile"
_MARKDOWN_SUFFIX = ".md"
_FRONTMATTER_DELIMITER = "---"
_ENABLED_KEY = "enabled"


def _ignore_migration_delivery(_destination: Destination) -> None:
    """Keep migration destinations outside project setup's return value."""


def _is_teleclaude_project(project_root: Path) -> bool:
    """Check if this is the TeleClaude project itself (not a user project)."""
    marker = project_root / "teleclaude" / "project_setup" / "init_flow.py"
    return marker.exists()


def _contains_file(directory: Path) -> bool:
    """Return whether a structural capability directory contains a file."""
    return directory.is_dir() and any(path.is_file() for path in directory.rglob("*"))


def _contains_doc_snippet(project_root: Path) -> bool:
    """Detect authored snippet frontmatter without treating any docs folder as a subscription."""
    docs_root = project_root / _DOCS_DIRECTORY
    if not docs_root.is_dir():
        return False
    for path in docs_root.rglob(f"*{_MARKDOWN_SUFFIX}"):
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                if handle.readline().strip() == _FRONTMATTER_DELIMITER:
                    return True
        except OSError:
            continue
    return False


def _inferred_capabilities(project_root: Path) -> dict[CapabilityName, bool]:
    """Infer subscriptions from durable project structure at first adoption."""
    return {
        CapabilityName.CODE: (project_root / _MAKEFILE_NAME).is_file() or bool(get_project_languages(project_root)),
        CapabilityName.DOCS: _contains_doc_snippet(project_root),
        CapabilityName.AGENTS: any(_contains_file(project_root / name) for name in _AGENT_DIRECTORIES),
    }


def _declare_inferred_capabilities(
    project_root: Path,
    undeclared_capabilities: frozenset[CapabilityName],
) -> Capabilities:
    """Materialize missing capability declarations while preserving explicit edits."""
    manifest_path = project_root / ConfigFileName.OVERLAY
    subject = registered_subject(manifest_path)
    if subject is None or subject.kind is not ConfigSubjectKind.PROJECT:
        raise ValueError(f"Project configuration is not registered: {manifest_path}")
    with file_transaction(manifest_path) as transaction:
        stored = round_trip_yaml().load(transaction.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            raise ValueError(f"Project configuration must be a YAML mapping: {manifest_path}")
        raw = dict(upcast(stored, subject))
        changed = False
        inferred = _inferred_capabilities(project_root)
        for capability in undeclared_capabilities:
            if capability.value in raw:
                continue
            raw[capability.value] = {_ENABLED_KEY: inferred[capability]}
            changed = True
        if changed:
            ProjectConfig.model_validate({**raw, "kind": ConfigKind.PROJECT.value})
            carry_pending(stored, subject, delivered=_ignore_migration_delivery)
            transaction.replace_text(render_declared_config(ConfigKind.PROJECT, raw))
    return resolve_capabilities(project_root)


def _ensure_project_slug(project_root: Path) -> None:
    """Ensure ``teleclaude.yml`` carries a valid ``project_slug`` entry.

    ``project_slug`` is the canonical machine identity used by the project
    catalog service, cross-project snippet resolution, and job subscription.
    When the config file already defines a valid slug we leave it alone; when
    absent, we derive one from ``project_name`` (or the directory name) and
    persist it via an in-place rewrite that preserves surrounding keys.

    ``ensure_project_config`` materializes a bare ``teleclaude.yml`` before
    initialization proceeds. Missing files and undecodable YAML raise
    :class:`RuntimeError` — ``project_slug`` is a hard init invariant, not an
    optional enhancement.
    """
    config_path = resolve_project_config_path(project_root)
    if not config_path.exists():
        raise RuntimeError(
            f"cannot write project_slug: {config_path} does not exist after configuration setup",
        )

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    try:
        raw = yaml_rt.load(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot read {config_path} to write project_slug: {exc}") from exc
    if not isinstance(raw, dict):
        raw = {}

    existing = raw.get("project_slug")
    if isinstance(existing, str) and existing.strip():
        try:
            validate_slug(existing.strip())
            return
        except ValueError:
            # Fall through and overwrite an invalid slug.
            pass

    seed = raw.get("project_name") if isinstance(raw.get("project_name"), str) else None
    slug = normalize_slug(seed or project_root.name)
    if not slug:
        raise RuntimeError(
            f"cannot derive a valid project_slug for {project_root}: "
            "neither project_name nor the directory name normalized to a usable slug",
        )

    raw["project_slug"] = slug
    buffer = io.StringIO()
    yaml_rt.dump(raw, buffer)
    config_path.write_text(buffer.getvalue(), encoding="utf-8")


def _ensure_trusted_directory(project_root: Path) -> None:
    """List a registered project among the machine's trusted directories.

    The trusted directories are the projects the operator's TUI shows. An entry
    that already names this root is left as it is, so a name or description the
    operator chose survives re-initialization.
    """
    resolved_root = project_root.resolve()
    for trusted_dir in config.computer.get_all_trusted_dirs():
        if Path(trusted_dir.path).expanduser().resolve() == resolved_root:
            return
    add_trusted_directory(get_project_slug(project_root), str(resolved_root))


def init_project(project_root: Path) -> None:
    """Initialize a project for TeleClaude — configuration and plumbing only.

    Configures git filters and project-owned hooks, converges plumbing,
    and registers the project root. Asks nothing: machine-wide settings such as
    the release channel belong to the machine configuration, not to a project.
    Idempotent and CI-safe; spawns no agent sessions and syncs no artifacts.

    Mother-aware: when invoked inside the TeleClaude repo itself, skeleton
    deployment is skipped — it only makes sense for downstream projects.

    AI-driven project analysis and quality-config assessment are explicit,
    separate acts started with ``telec sessions run --command
    /projects-analyze`` and ``telec sessions run --command
    /projects-assess-config`` — never a side effect of this function.
    """
    is_mother = _is_teleclaude_project(project_root)

    ensure_git_repo(project_root)
    # Establish the project configuration before the remaining setup steps.
    ensure_project_config(project_root)
    invocation_document = round_trip_yaml().load((project_root / ConfigFileName.OVERLAY).read_text(encoding="utf-8"))
    if not isinstance(invocation_document, dict):
        raise ValueError(f"Project configuration must be a YAML mapping: {project_root / ConfigFileName.OVERLAY}")
    undeclared_capabilities = frozenset(
        capability for capability in CapabilityName if capability.value not in invocation_document
    )
    registered_root = resolve_project_root(project_root)
    register_root(project_root=registered_root)
    migrate_document(
        registered_root / ConfigFileName.OVERLAY,
        SubjectRef(ConfigSubjectKind.PROJECT),
        MigrationTrigger.REGISTRATION,
    )
    capabilities = _declare_inferred_capabilities(project_root, undeclared_capabilities)
    if capabilities.docs:
        update_gitattributes(project_root)
    from teleclaude.project_setup.plumbing import converge_plumbing  # noqa: PLC0415 - avoids entrypoint preload.

    converge_plumbing(project_root)
    if not is_mother and capabilities.code:
        deploy_skeleton(project_root)
    _ensure_project_slug(project_root)
    _ensure_trusted_directory(registered_root)
    seed_event_domains(project_root)

    print("telec config project init complete.")


# ---------------------------------------------------------------------------
# Help desk bootstrap (inlined to avoid circular import with init_flow)
# ---------------------------------------------------------------------------


def _resolve_help_desk_dir() -> Path:
    """Resolve help desk directory from config or default sibling location."""
    configured = config.computer.help_desk_dir
    if configured:
        return Path(configured).expanduser().resolve()
    teleclaude_root = Path(__file__).resolve().parents[2]
    return teleclaude_root.parent / "help-desk"


def bootstrap_help_desk(project_root: Path) -> None:
    """Scaffold the help desk workspace if it does not exist.

    Idempotent: skips if the directory already exists. Calls ``init_project``
    on the new directory, which is why this lives in init_flow rather than a
    separate module. Project initialization does not invoke it.
    """
    help_desk_dir = _resolve_help_desk_dir()
    if help_desk_dir.exists():
        logger.info("help_desk_exists", path=str(help_desk_dir))
        return

    template_dir = project_root / "templates" / "help-desk"
    if not template_dir.exists():
        logger.warning("help_desk_template_missing", path=str(template_dir))
        return

    logger.info("help_desk_bootstrap_start", path=str(help_desk_dir))

    help_desk_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        help_desk_dir.mkdir()
    except FileExistsError:
        logger.info("help_desk_exists", path=str(help_desk_dir))
        return

    try:
        materialize_template_tree(
            template_dir,
            help_desk_dir,
            values={},
            # guard: direct-env-read - allowed: configuration loading or interpolation
            environ=os.environ,
        )
        repo = Repo.init(help_desk_dir)
        init_project(help_desk_dir)
        repo.git.add(".")
        repo.index.commit("Initial help desk scaffold")
    except Exception:
        shutil.rmtree(help_desk_dir, ignore_errors=True)
        raise

    logger.info("help_desk_bootstrap_complete", path=str(help_desk_dir))
