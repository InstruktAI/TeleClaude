"""Entrypoint for installed-code checkout purpose queries and companion reconciliation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from teleclaude.config.checkout_association import CheckoutPurpose, checkout_association_for
from teleclaude.core.checkout_roots import resolve_checkout_roots
from teleclaude.core.reconciliation.development_checkout import converge_development_checkout
from teleclaude.core.worktree_layout import development_home_for_checkout
from teleclaude.deployment.release_checkout import installed_checkout_root
from teleclaude.logging_config import setup_logging
from teleclaude.paths import TELECLAUDE_SOURCE_HOME

_PURPOSE_OPTION = "--purpose"
_HOME_OPTION = "--home"
_PURPOSE_INSTALLED = "installed"
_PURPOSE_DEVELOPMENT = "development"
_PURPOSE_WORKTREE = "worktree"
_PURPOSE_UNASSOCIATED = "unassociated"
_HOME_NOT_ASSOCIATED = "the requested checkout is not the registered development location"
_DEVELOPMENT_HOME_MISSING = (
    "the development checkout home is not provisioned; rerun installation from the installed checkout"
)
_NOT_READY = "Development checkout failed at {step}: {detail}"
_READY = "Development checkout ready: {path} (purpose: development)"
_NOT_APPLICABLE = "Development checkout provisioning is not applicable on this machine"
_NOT_APPLICABLE_EXIT = 3


def checkout_purpose(path: Path) -> str:
    """Report exact installed/development purpose without inferring it from the directory name."""
    target = path.expanduser().resolve()
    installed = installed_checkout_root()
    if installed is None:
        return _PURPOSE_UNASSOCIATED
    installed = installed.expanduser().resolve()
    if target == installed:
        return _PURPOSE_INSTALLED
    association = checkout_association_for(target, TELECLAUDE_SOURCE_HOME / "projects.yaml")
    if association is not None and target == association.development_checkout:
        return _PURPOSE_DEVELOPMENT
    roots = resolve_checkout_roots(target, registry_path=TELECLAUDE_SOURCE_HOME / "projects.yaml")
    if roots.purpose is CheckoutPurpose.DEVELOPMENT:
        return _PURPOSE_WORKTREE
    return _PURPOSE_UNASSOCIATED


def development_home(path: Path) -> Path:
    """Resolve the isolated home for the exact registered development checkout."""
    target = path.expanduser().resolve()
    if checkout_purpose(target) != _PURPOSE_DEVELOPMENT:
        raise ValueError(_HOME_NOT_ASSOCIATED)
    home = development_home_for_checkout(target)
    if not home.is_dir():
        raise ValueError(_DEVELOPMENT_HOME_MISSING)
    return home


def main(argv: list[str] | None = None) -> int:
    """Answer a purpose query or run full installed-checkout reconciliation."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    query = parser.add_mutually_exclusive_group()
    query.add_argument(_PURPOSE_OPTION, type=Path)
    query.add_argument(_HOME_OPTION, type=Path)
    args = parser.parse_args(argv)
    if args.purpose is not None:
        print(checkout_purpose(args.purpose))
        return 0
    if args.home is not None:
        try:
            print(development_home(args.home))
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    result = converge_development_checkout()
    if result.ready:
        if result.development_root is None:
            print(_NOT_APPLICABLE)
            return _NOT_APPLICABLE_EXIT
        else:
            print(_READY.format(path=result.development_root))
        return 0
    print(_NOT_READY.format(step=result.step or "preflight", detail=result.error or "unknown failure"), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
