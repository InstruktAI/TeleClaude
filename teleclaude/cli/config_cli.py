"""Programmatic CLI for TeleClaude configuration.

Provides subcommands for AI agents and scripts to manage config:
  telec config people list|add|edit|remove
  telec config env list|set
  telec config notify NAME --telegram on|off
  telec config validate

All subcommands support --json for machine-readable output.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from teleclaude.cli.config_handlers import (
    add_person,
    check_env_vars,
    get_person_config,
    list_people,
    remove_person,
    save_person_config,
    validate_all,
)
from teleclaude.config.schema import PersonEntry, TelegramCreds


def _check_customer_guard() -> None:
    """Block customer-role sessions from mutating config commands.

    Reads session ID from $TMPDIR/teleclaude_session_id and checks human_role
    via sync DB lookup. Skips check when not in a session context.
    """
    tmpdir = os.environ.get("TMPDIR", "")
    if not tmpdir:
        return
    marker = Path(tmpdir) / "teleclaude_session_id"
    if not marker.exists():
        return
    try:
        session_id = marker.read_text(encoding="utf-8").strip()
    except Exception:
        return
    if not session_id:
        return
    try:
        from teleclaude.config import config
        from teleclaude.core.db import get_session_field_sync

        role = get_session_field_sync(config.database.path, session_id, "human_role")
        if role in ("customer", "public"):
            print("Error: Permission denied. This operation requires member role or higher.")
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception:
        # DB unavailable or session not found — allow (fail open for human terminals)
        pass


@dataclass
class PersonInfo:
    """JSON-serializable person record."""

    name: str
    role: str
    email: str | None = None
    username: str | None = None
    telegram: str | None = None
    telegram_id: int | None = None
    notifications_telegram: bool = False
    interests: list[str] = field(default_factory=list)


def handle_config_cli(args: list[str]) -> None:
    """Route config subcommands to handlers."""
    if not args:
        print("Error: subcommand required. Use 'telec config --help'.")
        raise SystemExit(1)

    sub = args[0]
    rest = args[1:]

    handlers = {
        "people": _handle_people,
        "env": _handle_env,
        "notify": _handle_notify,
        "validate": _handle_validate,
        "invite": _handle_invite,
    }

    handler = handlers.get(sub)
    if not handler:
        print(f"Unknown config subcommand: {sub}")
        raise SystemExit(1)

    handler(rest)


# --- People ---


def _handle_people(args: list[str]) -> None:
    if not args:
        print("Usage: telec config people <list|add|edit|remove> [options]")
        raise SystemExit(1)

    action = args[0]
    rest = args[1:]
    use_json = "--json" in rest
    rest = [a for a in rest if a != "--json"]

    if action == "list":
        _people_list(use_json)
    elif action == "add":
        _people_add(rest, use_json)
    elif action == "edit":
        _people_edit(rest, use_json)
    elif action == "remove":
        _people_remove(rest, use_json)
    else:
        print(f"Unknown people action: {action}")
        raise SystemExit(1)


def _people_list(use_json: bool) -> None:
    people = list_people()
    if use_json:
        data = []
        for p in people:
            info = PersonInfo(name=p.name, role=p.role, email=p.email, username=p.username)
            try:
                pc = get_person_config(p.name)
                info.telegram = pc.creds.telegram.user_name if pc.creds.telegram else None
                info.telegram_id = pc.creds.telegram.user_id if pc.creds.telegram else None
                info.notifications_telegram = pc.notifications.telegram
                info.interests = list(pc.interests)
            except (ValueError, Exception):
                pass
            data.append(asdict(info))
        print(json.dumps(data, indent=2))
    else:
        if not people:
            print("No people configured.")
            return
        for p in people:
            print(f"  {p.name} ({p.role}){f' <{p.email}>' if p.email else ''}")


def _parse_kv_args(args: list[str]) -> dict[str, str]:
    """Parse --key value pairs from args list."""
    result: dict[str, str] = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--") and i + 1 < len(args):
            key = args[i][2:].replace("-", "_")
            result[key] = args[i + 1]
            i += 2
        else:
            i += 1
    return result


def _people_add(args: list[str], use_json: bool) -> None:
    _check_customer_guard()
    opts = _parse_kv_args(args)
    name = opts.get("name")
    if not name:
        print("Error: --name required")
        raise SystemExit(1)

    entry = PersonEntry(
        name=name,
        email=opts.get("email"),
        username=opts.get("username"),
        role=opts.get("role", "member"),  # type: ignore[arg-type]
    )

    try:
        add_person(entry)
    except ValueError as e:
        if use_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}")
        raise SystemExit(1)

    # Set telegram creds if provided
    if opts.get("telegram_user") or opts.get("telegram_id"):
        _set_telegram_creds(name, opts.get("telegram_user"), opts.get("telegram_id"))

    if use_json:
        print(json.dumps({"ok": True, "name": name, "role": entry.role}))
    else:
        print(f"Added {name} as {entry.role}.")


def _people_edit(args: list[str], use_json: bool) -> None:
    _check_customer_guard()
    if not args:
        print("Error: person name required")
        raise SystemExit(1)

    # First positional arg is the name
    name = args[0]
    opts = _parse_kv_args(args[1:])

    # Find person in global config
    people = list_people()
    person = next((p for p in people if p.name == name), None)
    if not person:
        msg = f"Person '{name}' not found"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}")
        raise SystemExit(1)

    changed = False

    # Edit global entry fields (role, email, username)
    if any(k in opts for k in ("role", "email", "username")):
        from teleclaude.cli.config_handlers import get_global_config, save_global_config

        config = get_global_config()
        for p in config.people:
            if p.name == name:
                if "role" in opts:
                    p.role = opts["role"]  # type: ignore[assignment]
                if "email" in opts:
                    p.email = opts["email"]
                if "username" in opts:
                    p.username = opts["username"]
                changed = True
                break
        if changed:
            save_global_config(config)

    # Edit telegram creds
    if opts.get("telegram_user") or opts.get("telegram_id"):
        _set_telegram_creds(name, opts.get("telegram_user"), opts.get("telegram_id"))
        changed = True

    # Edit notifications
    if "notifications_telegram" in opts:
        pc = get_person_config(name)
        pc.notifications.telegram = opts["notifications_telegram"].lower() in ("true", "on", "1", "yes")
        save_person_config(name, pc)
        changed = True

    if not changed:
        msg = "No changes specified. Use --role, --email, --username, --telegram-user, --telegram-id, --notifications-telegram"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}")
        raise SystemExit(1)

    if use_json:
        print(json.dumps({"ok": True, "name": name, "updated": list(opts.keys())}))
    else:
        print(f"Updated {name}: {', '.join(opts.keys())}.")


def _people_remove(args: list[str], use_json: bool) -> None:
    _check_customer_guard()
    if not args:
        print("Error: person name required")
        raise SystemExit(1)

    name = args[0]
    delete_dir = "--delete-dir" in args

    try:
        remove_person(name, delete_directory=delete_dir)
    except ValueError as e:
        if use_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}")
        raise SystemExit(1)

    if use_json:
        print(json.dumps({"ok": True, "name": name, "directory_deleted": delete_dir}))
    else:
        print(f"Removed {name}.{' Directory deleted.' if delete_dir else ''}")


def _set_telegram_creds(name: str, user_name: str | None, user_id: str | None) -> None:
    """Set telegram credentials for a person."""
    pc = get_person_config(name)
    existing = pc.creds.telegram

    tg_user = user_name or (existing.user_name if existing else None)
    tg_id = user_id or (str(existing.user_id) if existing else None)

    if tg_user and tg_id:
        pc.creds.telegram = TelegramCreds(user_name=tg_user, user_id=int(tg_id))
        save_person_config(name, pc)


# --- Env ---


def _handle_env(args: list[str]) -> None:
    if not args:
        print("Usage: telec config env <list|set> [options]")
        raise SystemExit(1)

    action = args[0]
    rest = args[1:]

    if action == "list":
        use_json = "--json" in rest
        _env_list(use_json)
    elif action == "set":
        use_json = "--json" in rest
        pairs = [a for a in rest if a != "--json" and "=" in a]
        _env_set(pairs, use_json)
    else:
        print(f"Unknown env action: {action}")
        raise SystemExit(1)


def _env_list(use_json: bool) -> None:
    statuses = check_env_vars()
    if use_json:
        data = [
            {
                "name": s.info.name,
                "service": s.info.adapter,
                "is_set": s.is_set,
                "description": s.info.description,
            }
            for s in statuses
        ]
        print(json.dumps(data, indent=2))
    else:
        for s in statuses:
            icon = "\u2713" if s.is_set else "\u2717"
            print(f"  {icon} {s.info.name} ({s.info.adapter}): {'set' if s.is_set else 'NOT SET'}")


def _env_set(pairs: list[str], use_json: bool) -> None:
    _check_customer_guard()
    if not pairs:
        print("Error: provide KEY=VALUE pairs")
        raise SystemExit(1)

    env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    results = []

    for pair in pairs:
        key, _, value = pair.partition("=")
        if not key or not value:
            continue
        _write_env_var(env_file, key, value)
        os.environ[key] = value
        results.append({"name": key, "set": True})

    if use_json:
        print(json.dumps({"ok": True, "updated": results}))
    else:
        for r in results:
            print(f"  Set {r['name']} in .env")
        print("\n  Restart the daemon (make restart) to pick up changes.")


def _write_env_var(env_file: Path, name: str, value: str) -> None:
    """Set or update a variable in the .env file."""
    lines: list[str] = []
    found = False

    if env_file.exists():
        lines = env_file.read_text().splitlines(keepends=True)
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(f"{name}=") or stripped.startswith(f"export {name}="):
                lines[i] = f"{name}={value}\n"
                found = True
                break

    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{name}={value}\n")

    env_file.write_text("".join(lines))


# --- Notify ---


def _handle_notify(args: list[str]) -> None:
    _check_customer_guard()
    use_json = "--json" in args
    args = [a for a in args if a != "--json"]

    if len(args) < 1:
        print("Usage: telec config notify NAME --telegram on|off")
        raise SystemExit(1)

    name = args[0]
    opts = _parse_kv_args(args[1:])

    try:
        pc = get_person_config(name)
    except (ValueError, Exception) as e:
        if use_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}")
        raise SystemExit(1)

    changed = {}
    if "telegram" in opts:
        pc.notifications.telegram = opts["telegram"].lower() in ("on", "true", "1", "yes")
        changed["telegram"] = pc.notifications.telegram

    if not changed:
        print("Error: specify --telegram on|off")
        raise SystemExit(1)

    save_person_config(name, pc)

    if use_json:
        print(json.dumps({"ok": True, "name": name, "notifications": changed}))
    else:
        for k, v in changed.items():
            print(f"  {name}: {k} notifications {'enabled' if v else 'disabled'}.")


# --- Validate ---


def _handle_validate(args: list[str]) -> None:
    use_json = "--json" in args

    results = validate_all()

    if use_json:
        data = [
            {
                "area": r.area,
                "passed": r.passed,
                "errors": r.errors,
                "suggestions": r.suggestions,
            }
            for r in results
        ]
        all_passed = all(r.passed for r in results)
        print(json.dumps({"ok": all_passed, "results": data}, indent=2))
    else:
        for r in results:
            icon = "\u2713" if r.passed else "\u2717"
            print(f"  {icon} {r.area}")
            for err in r.errors:
                print(f"    Error: {err}")
            for sug in r.suggestions:
                print(f"    Fix: {sug}")

        all_passed = all(r.passed for r in results)
        if not all_passed:
            raise SystemExit(1)


# --- Invite ---


def _handle_invite(args: list[str]) -> None:
    _check_customer_guard()
    use_json = "--json" in args
    args_clean = [a for a in args if a != "--json"]

    if not args_clean:
        print("Usage: telec config invite NAME [--adapters telegram,discord]")
        raise SystemExit(1)

    name = args_clean[0]
    opts = _parse_kv_args(args_clean[1:])
    adapters = [a.strip() for a in opts.get("adapters", "telegram").split(",")]

    # Verify person exists
    people = list_people()
    person = next((p for p in people if p.name == name), None)
    if not person:
        msg = f"Person '{name}' not found"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}")
        raise SystemExit(1)

    # Generate invite links
    links: dict[str, str | None] = {}
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    for adapter in adapters:
        if adapter == "telegram" and bot_token:
            # Telegram deep link: t.me/BOT_USERNAME?start=PAYLOAD
            # Bot username can be fetched from token, but for now use a placeholder
            # that the admin can fill in or that gets resolved at send time
            links["telegram"] = f"https://t.me/?start=invite_{name.replace(' ', '_').lower()}"
        else:
            links[adapter] = None

    if use_json:
        print(json.dumps({"ok": True, "name": name, "links": links}))
    else:
        print(f"  Invite links for {name}:")
        for adapter, link in links.items():
            if link:
                print(f"    {adapter}: {link}")
            else:
                print(f"    {adapter}: not available (missing credentials or token)")
