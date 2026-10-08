"""Deploy tier documentation and compile entrypoints for individual homes."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

import yaml

from teleclaude.artifact_ownership import retired_pointer_candidate
from teleclaude.config.schema import ConfigKind
from teleclaude.docs_index import reroot_index_document
from teleclaude.docs_publication import publish_generation
from teleclaude.docs_publishers import DocsResolutionMode
from teleclaude.install.distribution import (
    GENERATED_ENTRYPOINT_FILENAME,
    HELP_DESK_DIRNAME,
    INDEX_DEPLOY_ROOT,
    INDEX_FILE_NAME,
    INDEX_PROJECT_ROOT_KEY,
    INDEX_SCOPE_ROOT,
    INDEX_SNIPPETS_KEY,
    INDEX_SNIPPETS_ROOT_KEY,
    PROJECT_MASTER_FILENAME,
    SOURCE_PROJECT_KEY,
    TIER_COMPANY_DEPLOY_DIRNAME,
    TIER_PERSON_DEPLOY_DIRNAME,
    TIER_PUBLISHED_DOCS_RELATIVE_PATH,
    UTF8,
    DistributionObservation,
    EntrypointCompositionError,
    HomeMasterInflationError,
    index_entry_sort_key,
    inflate_master,
)
from teleclaude.paths import GLOBAL_DOCS_DIR

_COMPANY_SOURCE_PROJECT_PREFIX: Final = "company:"
_PERSON_SOURCE_PROJECT_PREFIX: Final = "person:"
_INDEX_PATH_KEY: Final = "path"
_DEPLOYED_DOCS_DIRECTORY: Final = Path("docs")
_UNSUPPORTED_TIER_KIND: Final = "Tier deployment does not support home kind {kind}"
_DOCS_STAGING_PREFIX: Final = ".docs.next-"
_INVALID_DEPLOYED_INDEX: Final = "Deployed documentation index is malformed: {path}"


class TierHome(NamedTuple):
    """One committed tier contribution to the deployed documentation corpus."""

    root: Path
    kind: ConfigKind
    slug: str


@dataclass(frozen=True)
class HomeEntrypoint:
    """One home master's compiled entrypoint text, rooted in the home snapshot."""

    master: Path
    output: Path
    text: str


@dataclass(frozen=True)
class HomeEntrypoints:
    """Every compiled home entrypoint plus the pointer paths beside their masters."""

    entrypoints: tuple[HomeEntrypoint, ...]
    retired_pointers: tuple[Path, ...]


def distribute_tier_homes(
    tier_homes: list[TierHome],
    retracted: set[tuple[ConfigKind, str]],
    deploy_docs_root: Path = GLOBAL_DOCS_DIR,
) -> None:
    """Replace selected tier contributions and retract absent homes in one generation."""
    staged_root = Path(tempfile.mkdtemp(prefix=_DOCS_STAGING_PREFIX, dir=deploy_docs_root.parent))
    try:
        if deploy_docs_root.is_dir():
            shutil.copytree(deploy_docs_root, staged_root, dirs_exist_ok=True, symlinks=False)

        replaced = {(home.kind, home.slug) for home in tier_homes}
        affected = replaced | retracted
        existing_index = staged_root / INDEX_FILE_NAME
        existing_entries = _deployed_index_entries(existing_index) if existing_index.is_file() else []
        tier_identity_values = {_source_project_value(kind, slug) for kind, slug in affected}
        retained = [
            entry
            for entry in existing_entries
            if not (isinstance(entry, dict) and entry.get(SOURCE_PROJECT_KEY) in tier_identity_values)
        ]
        for kind, slug in affected:
            deploy_dirname = _tier_deploy_dirname(kind)
            stale = staged_root / deploy_dirname / slug
            if stale.is_dir():
                shutil.rmtree(stale)

        tier_entries: list[object] = []
        for home in tier_homes:
            deploy_dirname = _tier_deploy_dirname(home.kind)
            staged_tier_root = staged_root / deploy_dirname / home.slug
            deployed_tier_root = deploy_docs_root / deploy_dirname / home.slug
            source_docs = home.root / TIER_PUBLISHED_DOCS_RELATIVE_PATH
            if source_docs.is_dir():
                shutil.copytree(source_docs, staged_tier_root, symlinks=False)
            else:
                staged_tier_root.mkdir(parents=True, exist_ok=True)
            snapshot_index_text = (source_docs / INDEX_FILE_NAME).read_text(encoding=UTF8)
            rerooted_text = reroot_index_document(snapshot_index_text, source_docs, deployed_tier_root)
            (staged_tier_root / INDEX_FILE_NAME).write_text(rerooted_text, encoding=UTF8)
            payload = yaml.safe_load(rerooted_text)
            source_project_value = _source_project_value(home.kind, home.slug)
            for entry in payload[INDEX_SNIPPETS_KEY]:
                tier_entries.append(
                    {
                        **entry,
                        _INDEX_PATH_KEY: (
                            _DEPLOYED_DOCS_DIRECTORY / deploy_dirname / home.slug / entry[_INDEX_PATH_KEY]
                        ).as_posix(),
                        SOURCE_PROJECT_KEY: source_project_value,
                    }
                )

        merged_entries: list[object] = [*retained, *tier_entries]
        merged_entries.sort(key=index_entry_sort_key)
        index_path = staged_root / INDEX_FILE_NAME
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
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
        previous_root = publish_generation(staged_root, deploy_docs_root)
    except Exception:
        shutil.rmtree(staged_root, ignore_errors=True)
        raise
    if previous_root is not None:
        if previous_root.is_symlink():
            previous_root.unlink()
        else:
            shutil.rmtree(previous_root)


def home_master_candidates(home_snapshot: Path, kind: ConfigKind) -> list[tuple[Path, Path]]:
    """Return the fixed set of masters a home of this kind can own with their read roots, present or not."""
    candidates = [(home_snapshot / PROJECT_MASTER_FILENAME, home_snapshot)]
    if kind in (ConfigKind.GLOBAL, ConfigKind.COMPANY):
        candidates.append((home_snapshot / HELP_DESK_DIRNAME / PROJECT_MASTER_FILENAME, home_snapshot))
    return candidates


def home_masters(home_snapshot: Path, kind: ConfigKind) -> list[tuple[Path, Path]]:
    """Return only the masters owned by one home with their read roots."""
    return [(master, root) for master, root in home_master_candidates(home_snapshot, kind) if master.is_file()]


def inflate_home_entrypoint(
    master: Path, *, project_root: Path, observation: DistributionObservation | None
) -> HomeEntrypoint:
    """Compile one home master against the deployed corpus."""
    try:
        text = inflate_master(
            master,
            project_root=project_root,
            root_extras=False,
            warn_only=False,
            observation=observation,
            resolution=DocsResolutionMode.DEPLOYED,
        )
    except EntrypointCompositionError as exc:
        raise HomeMasterInflationError(master, exc) from exc
    return HomeEntrypoint(master=master, output=master.parent / GENERATED_ENTRYPOINT_FILENAME, text=text)


def inflate_home_entrypoints(
    home_snapshot: Path,
    kind: ConfigKind,
    *,
    observation: DistributionObservation | None = None,
) -> HomeEntrypoints:
    """Compile every master owned by one home, failing on the first invalid master."""
    masters = home_masters(home_snapshot, kind)
    return HomeEntrypoints(
        entrypoints=tuple(
            inflate_home_entrypoint(master, project_root=root, observation=observation) for master, root in masters
        ),
        retired_pointers=tuple(retired_pointer_candidate(master.parent) for master, _ in masters),
    )


def _tier_deploy_dirname(kind: ConfigKind) -> str:
    """Return the deployed directory for a company or person home."""
    if kind is ConfigKind.COMPANY:
        return TIER_COMPANY_DEPLOY_DIRNAME
    if kind is ConfigKind.PERSON:
        return TIER_PERSON_DEPLOY_DIRNAME
    raise ValueError(_UNSUPPORTED_TIER_KIND.format(kind=kind.value))


def _source_project_value(kind: ConfigKind, slug: str) -> str:
    """Return the existing merged-index identity for one tier home."""
    prefix = _COMPANY_SOURCE_PROJECT_PREFIX if kind is ConfigKind.COMPANY else _PERSON_SOURCE_PROJECT_PREFIX
    return f"{prefix}{slug}"


def _deployed_index_entries(path: Path) -> list[object]:
    """Read the deployed index entries, refusing malformed existing state."""
    try:
        payload: object = yaml.safe_load(path.read_text(encoding=UTF8))
    except yaml.YAMLError as exc:
        raise ValueError(_INVALID_DEPLOYED_INDEX.format(path=path)) from exc
    if not isinstance(payload, dict):
        raise ValueError(_INVALID_DEPLOYED_INDEX.format(path=path))
    entries = payload.get(INDEX_SNIPPETS_KEY)
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError(_INVALID_DEPLOYED_INDEX.format(path=path))
    return entries


def deployed_tier_identities(deploy_docs_root: Path = GLOBAL_DOCS_DIR) -> set[tuple[ConfigKind, str]]:
    """Read the tier identities currently recorded in the deployed merged index."""
    index_path = deploy_docs_root / INDEX_FILE_NAME
    if not index_path.is_file():
        return set()
    entries = _deployed_index_entries(index_path)
    identities: set[tuple[ConfigKind, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_project = entry.get(SOURCE_PROJECT_KEY)
        if not isinstance(source_project, str):
            continue
        if source_project.startswith(_COMPANY_SOURCE_PROJECT_PREFIX):
            identities.add((ConfigKind.COMPANY, source_project.removeprefix(_COMPANY_SOURCE_PROJECT_PREFIX)))
        elif source_project.startswith(_PERSON_SOURCE_PROJECT_PREFIX):
            identities.add((ConfigKind.PERSON, source_project.removeprefix(_PERSON_SOURCE_PROJECT_PREFIX)))
    return identities
