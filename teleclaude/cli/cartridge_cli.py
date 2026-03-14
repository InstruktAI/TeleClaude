"""CLI surface for cartridge lifecycle management.

Handles:
  telec config cartridges install --path <src> --scope <scope> --target <name>
  telec config cartridges remove --id <id> --scope <scope> --target <name>
  telec config cartridges promote --id <id> --from <scope> --to <scope> --domain <name>
  telec config cartridges promote --from sandbox --to domain --domain <name> --id <name>
  telec config cartridges list [--scope sandbox] [--domain <name>] [--member <id>]
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from teleclaude.cli.session_auth import resolve_cli_caller_role
from teleclaude.constants import HUMAN_ROLE_ADMIN

if TYPE_CHECKING:
    from teleclaude.events.lifecycle import LifecycleManager

_DEFAULT_SANDBOX_DIR = Path("~/.teleclaude/sandbox-cartridges")


def _get_lifecycle_manager() -> LifecycleManager:
    """Build a LifecycleManager from global config."""
    from teleclaude.config.loader import load_global_config
    from teleclaude.events.lifecycle import LifecycleManager

    config = load_global_config()
    event_domains = getattr(config, "event_domains", None)

    if event_domains is not None:
        base_path = Path(event_domains.base_path).expanduser()
        personal_base = Path(event_domains.personal_base_path).expanduser()
    else:
        base_path = Path("~/.teleclaude/company").expanduser()
        personal_base = Path("~/.teleclaude/personal").expanduser()

    return LifecycleManager(
        personal_base_path=personal_base,
        domain_base_path=base_path,
    )


def _caller_is_admin() -> bool:
    """Determine if the current session caller has admin role."""
    return resolve_cli_caller_role() == HUMAN_ROLE_ADMIN


def _get_sandbox_dir() -> Path:
    """Resolve the sandbox cartridges directory."""
    try:
        from teleclaude.config.loader import load_global_config  # pylint: disable=import-outside-toplevel

        config = load_global_config()
        sandbox_dir = getattr(config, "sandbox_cartridges_dir", None)
        if sandbox_dir:
            return Path(sandbox_dir).expanduser()
    except Exception as exc:
        print(f"Warning: could not load sandbox_cartridges_dir from config: {exc}", file=sys.stderr)
    return _DEFAULT_SANDBOX_DIR.expanduser()


def _list_sandbox_cartridges(use_json: bool) -> None:
    """List cartridges in the sandbox cartridges directory."""
    sandbox_dir = _get_sandbox_dir()
    if not sandbox_dir.exists():
        if use_json:
            print(json.dumps([]))
        else:
            print(f"No sandbox cartridges directory at {sandbox_dir}")
        return

    rows = []
    for path in sorted(sandbox_dir.glob("*.py")):
        stat = path.stat()
        rows.append({
            "id": path.stem,
            "file": path.name,
            "size_bytes": stat.st_size,
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })

    if use_json:
        print(json.dumps(rows))
    else:
        if not rows:
            print(f"No sandbox cartridges in {sandbox_dir}")
        else:
            print(f"{'ID':<30} {'SIZE':>8}  MODIFIED            FILE")
            print("-" * 75)
            for row in rows:
                print(f"{row['id']:<30} {row['size_bytes']:>8}  {row['modified']}  {row['file']}")


def _promote_from_sandbox(parsed: argparse.Namespace, use_json: bool) -> None:
    """Promote a sandbox cartridge (.py file) into the lifecycle cartridge directory."""
    cartridge_id = parsed.cartridge_id
    to_scope = parsed.to_scope
    target_domain = getattr(parsed, "target_domain", None)

    if to_scope != "domain" or not target_domain:
        print("Error: --from sandbox requires --to domain --domain <name>", file=sys.stderr)
        sys.exit(1)

    sandbox_dir = _get_sandbox_dir()
    src = sandbox_dir / f"{cartridge_id}.py"

    if not src.exists():
        print(f"Error: sandbox cartridge '{cartridge_id}.py' not found in {sandbox_dir}", file=sys.stderr)
        sys.exit(1)

    # Syntax check
    try:
        ast.parse(src.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        print(f"Error: syntax error in '{src.name}': {exc}", file=sys.stderr)
        sys.exit(1)

    # Resolve lifecycle domain cartridge directory
    try:
        from teleclaude.config.loader import load_global_config  # pylint: disable=import-outside-toplevel

        config = load_global_config()
        event_domains = getattr(config, "event_domains", None)
        if event_domains is not None:
            domain_base = Path(event_domains.base_path).expanduser()
        else:
            domain_base = Path("~/.teleclaude/company").expanduser()
    except Exception:
        domain_base = Path("~/.teleclaude/company").expanduser()

    dest_dir = domain_base / "domains" / target_domain / "cartridges"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    shutil.copy2(src, dest)
    src.unlink()

    if use_json:
        print(json.dumps({"ok": True, "action": "promote", "id": cartridge_id, "from": "sandbox", "to": to_scope,
                          "domain": target_domain, "dest": str(dest)}))
    else:
        print(f"Promoted {src.name} to domain/{target_domain}/cartridges/")
        print("Next: wire it into the domain pipeline configuration, then commit.")


def handle_cartridge_cli(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="telec config cartridges", add_help=True)
    subparsers = parser.add_subparsers(dest="action")

    # install
    p_install = subparsers.add_parser("install", help="Install a cartridge")
    p_install.add_argument("--path", required=True, help="Source cartridge directory path")
    p_install.add_argument("--scope", required=True, choices=["personal", "domain", "platform"])
    p_install.add_argument("--target", required=True, help="Target name (member id or domain name)")
    p_install.add_argument("--json", action="store_true", help="Output JSON")

    # remove
    p_remove = subparsers.add_parser("remove", help="Remove a cartridge")
    p_remove.add_argument("--id", required=True, dest="cartridge_id", help="Cartridge ID")
    p_remove.add_argument("--scope", required=True, choices=["personal", "domain", "platform"])
    p_remove.add_argument("--target", required=True, help="Target name")
    p_remove.add_argument("--json", action="store_true", help="Output JSON")

    # promote
    p_promote = subparsers.add_parser("promote", help="Promote a cartridge to a higher scope")
    p_promote.add_argument("--id", required=True, dest="cartridge_id", help="Cartridge ID")
    p_promote.add_argument(
        "--from", required=True, dest="from_scope", choices=["personal", "domain", "platform", "sandbox"]
    )
    p_promote.add_argument("--to", required=True, dest="to_scope", choices=["personal", "domain", "platform"])
    p_promote.add_argument("--domain", required=False, default=None, dest="target_domain", help="Target domain name")
    p_promote.add_argument(
        "--member", default=None, dest="source_member_id", help="Source member id (required when --from=personal)"
    )
    p_promote.add_argument("--json", action="store_true", help="Output JSON")

    # list
    p_list = subparsers.add_parser("list", help="List installed cartridges")
    p_list.add_argument("--scope", default=None, choices=["personal", "domain", "platform", "sandbox"],
                        help="Filter by scope (sandbox lists ~/.teleclaude/sandbox-cartridges/)")
    p_list.add_argument("--domain", default=None, help="Filter by domain name")
    p_list.add_argument("--member", default=None, help="Filter by member id")
    p_list.add_argument("--json", action="store_true", help="Output JSON")

    parsed = parser.parse_args(args)

    if parsed.action is None:
        parser.print_help()
        sys.exit(1)

    from teleclaude.events.lifecycle import CartridgeScope

    try:
        manager = _get_lifecycle_manager()
        is_admin = _caller_is_admin()
        use_json = getattr(parsed, "json", False)

        if parsed.action == "install":
            manager.install(
                source_path=Path(parsed.path).expanduser(),
                scope=CartridgeScope(parsed.scope),
                target=parsed.target,
                caller_is_admin=is_admin,
            )
            result = {"ok": True, "action": "install", "scope": parsed.scope, "target": parsed.target}
            if use_json:
                print(json.dumps(result))
            else:
                print(f"Installed cartridge from {parsed.path} to {parsed.scope}/{parsed.target}")

        elif parsed.action == "remove":
            manager.remove(
                cartridge_id=parsed.cartridge_id,
                scope=CartridgeScope(parsed.scope),
                target=parsed.target,
                caller_is_admin=is_admin,
            )
            result = {"ok": True, "action": "remove", "id": parsed.cartridge_id}
            if use_json:
                print(json.dumps(result))
            else:
                print(f"Removed cartridge '{parsed.cartridge_id}' from {parsed.scope}/{parsed.target}")

        elif parsed.action == "promote":
            if parsed.from_scope == "sandbox":
                _promote_from_sandbox(parsed, use_json)
            else:
                if not parsed.target_domain:
                    print("Error: --domain is required when promoting between lifecycle scopes", file=sys.stderr)
                    sys.exit(1)
                manager.promote(
                    cartridge_id=parsed.cartridge_id,
                    from_scope=CartridgeScope(parsed.from_scope),
                    to_scope=CartridgeScope(parsed.to_scope),
                    target_domain=parsed.target_domain,
                    caller_is_admin=is_admin,
                    source_member_id=getattr(parsed, "source_member_id", None),
                )
                result = {
                    "ok": True,
                    "action": "promote",
                    "id": parsed.cartridge_id,
                    "from": parsed.from_scope,
                    "to": parsed.to_scope,
                }
                if use_json:
                    print(json.dumps(result))
                else:
                    print(
                        f"Promoted cartridge '{parsed.cartridge_id}' from {parsed.from_scope} to {parsed.to_scope}"
                    )

        elif parsed.action == "list":
            scope_filter = getattr(parsed, "scope", None)
            if scope_filter == "sandbox":
                _list_sandbox_cartridges(use_json)
                return

            rows: list[dict[str, str]] = []
            if parsed.domain:
                rows.extend(manager.list_cartridges(CartridgeScope.domain, parsed.domain))
            elif parsed.member:
                rows.extend(manager.list_cartridges(CartridgeScope.personal, parsed.member))
            else:
                # List all domains from config
                from teleclaude.config.loader import load_global_config  # pylint: disable=import-outside-toplevel

                config = load_global_config()
                event_domains = getattr(config, "event_domains", None)
                if event_domains:
                    for domain_name in event_domains.domains:
                        rows.extend(manager.list_cartridges(CartridgeScope.domain, domain_name))
            if use_json:
                print(json.dumps(rows))
            else:
                if not rows:
                    print("No cartridges found.")
                else:
                    print(f"{'ID':<30} {'VERSION':<10} {'SCOPE':<10} {'TARGET':<20} DESCRIPTION")
                    print("-" * 90)
                    for row in rows:
                        print(
                            f"{row['id']:<30} {row['version']:<10} {row['scope']:<10} "
                            f"{row['target']:<20} {row['description']}"
                        )

    except PermissionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
