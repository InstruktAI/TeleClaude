"""Programmatic CLI for TeleClaude configuration.

Provides subcommands for AI agents and scripts to manage config:
  telec config people list|add|edit|remove
  telec config env list|set
  telec config notify NAME --telegram on|off
  telec config validate

All subcommands support --json for machine-readable output.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.cli.config_handlers import (
    add_person,
    check_env_vars,
    get_global_config,
    get_person_config,
    list_people,
    remove_person,
    save_global_config,
    save_person_config,
    set_invite_token,
    validate_all,
)
from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _maybe_show_help, _usage
from teleclaude.cli.telec.surface import (
    CONFIG_ENV_LIST,
    CONFIG_ENV_SET,
    CONFIG_NOTIFY,
    CONFIG_PEOPLE_ADD,
    CONFIG_PEOPLE_EDIT,
    CONFIG_PEOPLE_INVITE,
    CONFIG_PEOPLE_LIST,
    CONFIG_PEOPLE_REMOVE,
    CONFIG_VALIDATE,
)
from teleclaude.config import config
from teleclaude.config.migrations import migrate_person_slugs_if_needed
from teleclaude.config.schema import PersonEntry, TelegramCreds
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.identity import get_identity_resolver
from teleclaude.invite import (
    generate_invite_links,
    resolve_discord_bot_user_id,
    resolve_telegram_bot_username,
    send_invite_email,
)
from teleclaude.paths import PEOPLE_DIR, PROJECT_ENV_PATH
from teleclaude.slug import ensure_unique_slug, normalize_slug

logger = get_logger(__name__)


class InviteResult(TypedDict):
    """Result of invite generation."""

    ok: bool
    name: str
    email: str
    links: dict[str, str | None]
    email_sent: bool


def _check_customer_guard() -> None:
    """Block customer-role sessions from mutating config commands."""
    email = read_current_session_email()
    role = get_identity_resolver().resolve_by_email(email).person_role if email else None
    if role == HUMAN_ROLE_CUSTOMER:
        print("Error: Permission denied. This operation requires member role or higher.")
        raise SystemExit(1)


@dataclass
class PersonInfo:
    """JSON-serializable person record."""

    name: str
    role: str
    slug: str | None = None
    email: str | None = None
    username: str | None = None
    expertise: dict[str, str | dict[str, str]] | None = None
    telegram: str | None = None
    telegram_id: int | None = None
    interests: list[str] = field(default_factory=list)


def handle_config_cli(args: list[str]) -> None:
    """Route config subcommands to handlers."""
    if not args:
        print("Error: subcommand required. Use 'telec config --help'.")
        raise SystemExit(1)

    sub = args[0]
    rest = args[1:]

    # Intercept --help/-h at any level (e.g. "telec config people -h")
    if sub in ("--help", "-h") or "--help" in rest or "-h" in rest:
        _maybe_show_help("config", args)
        return

    handlers = {
        "people": _handle_people,
        "env": _handle_env,
        "notify": _handle_notify,
        "validate": _handle_validate,
    }

    handler = handlers.get(sub)
    if not handler:
        print(f"Unknown config subcommand: {sub}")
        raise SystemExit(1)

    handler(rest)


# --- People ---


def _handle_people(args: list[str]) -> None:
    if not args:
        print(_usage("config", "people"))
        raise SystemExit(1)

    action = args[0]
    rest = args[1:]

    # Ensure every person has a slug before any folder-keyed access in non-daemon CLI usage.
    migrate_person_slugs_if_needed()

    if action == "list":
        _people_list(rest)
    elif action == "add":
        _people_add(rest)
    elif action == "edit":
        _people_edit(rest)
    elif action == "remove":
        _people_remove(rest)
    elif action == "invite":
        _handle_invite(rest)
    else:
        print(f"Unknown people action: {action}")
        raise SystemExit(1)


def _people_list(args: list[str]) -> None:
    parsed = parse_command_args(CONFIG_PEOPLE_LIST, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)

    people = list_people()
    if use_json:
        data = []
        for p in people:
            info = PersonInfo(
                name=p.name,
                role=p.role,
                slug=p.slug,
                email=p.email,
                username=p.username,
                expertise=getattr(p, "expertise", None),
            )
            try:
                pc = get_person_config(p.slug or normalize_slug(p.name))
                info.telegram = pc.creds.telegram.user_name if pc.creds.telegram else None
                info.telegram_id = pc.creds.telegram.user_id if pc.creds.telegram else None
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
            slug_part = f" [{p.slug}]" if p.slug else ""
            print(f"  {p.name}{slug_part} ({p.role}){f' <{p.email}>' if p.email else ''}")


def _people_add(args: list[str]) -> None:
    _check_customer_guard()
    parsed = parse_command_args(CONFIG_PEOPLE_ADD, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Error: unexpected argument")
        raise SystemExit(1)
    name = positionals[0] if positionals else parsed.value(F.FLAG_PEOPLE_NAME_ALIAS)
    if not name:
        print("Error: --name required")
        raise SystemExit(1)

    email = parsed.value(F.FLAG_PEOPLE_EMAIL)
    if not email:
        print("Error: --email required")
        raise SystemExit(1)

    no_invite = parsed.has(F.FLAG_PEOPLE_NO_INVITE) or use_json

    expertise_raw = parsed.value(F.FLAG_PEOPLE_EXPERTISE)
    expertise = None
    if expertise_raw:
        try:
            expertise = json.loads(expertise_raw)
        except json.JSONDecodeError as e:
            print(f"Error: --expertise must be valid JSON: {e}")
            raise SystemExit(1) from e
    existing_slugs = {p.slug for p in list_people() if p.slug}
    base = normalize_slug(name) or "person"
    slug = ensure_unique_slug(PEOPLE_DIR, base, reserved=existing_slugs)

    entry = PersonEntry(
        name=name,
        email=email,
        slug=slug,
        username=parsed.value(F.FLAG_PEOPLE_USERNAME),
        role=parsed.value(F.FLAG_PEOPLE_ROLE) or "member",  # type: ignore[arg-type]
        expertise=expertise,
    )

    try:
        add_person(entry)
    except ValueError as e:
        if use_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}")
        raise SystemExit(1) from e

    # Set telegram creds if provided
    telegram_user = parsed.value(F.FLAG_PEOPLE_TELEGRAM_USER)
    telegram_id = parsed.value(F.FLAG_PEOPLE_TELEGRAM_ID)
    if telegram_user or telegram_id:
        _set_telegram_creds(name, telegram_user, telegram_id)

    # Auto-invite unless --no-invite is passed
    invite_sent = False
    if not no_invite:

        async def _run_auto_invite() -> bool:
            try:
                # Generate token
                token = set_invite_token(name)

                # Resolve bot usernames/IDs
                telegram_username = None
                discord_bot_id = None

                try:
                    telegram_username = await resolve_telegram_bot_username()
                except ValueError as e:
                    logger.warning("Failed to resolve Telegram bot username: %s", e)

                try:
                    discord_bot_id = await resolve_discord_bot_user_id()
                except ValueError as e:
                    logger.warning("Failed to resolve Discord bot user ID: %s", e)

                whatsapp_number = config.whatsapp.business_number

                # Generate links
                links = generate_invite_links(token, telegram_username, discord_bot_id, whatsapp_number)

                # Send email
                await send_invite_email(name, email, links)
                return True
            except Exception as e:
                logger.warning("Auto-invite failed for %s: %s", name, e)
                return False

        invite_sent = asyncio.run(_run_auto_invite())

    if use_json:
        result = {"ok": True, "name": name, "role": entry.role}
        if invite_sent:
            result["invite_sent"] = True
        print(json.dumps(result))
    else:
        if invite_sent:
            print(f"Added {name} as {entry.role} — invite sent to {email}")
        else:
            print(f"Added {name} as {entry.role}.")


def _people_edit(args: list[str]) -> None:
    _check_customer_guard()
    parsed = parse_command_args(CONFIG_PEOPLE_EDIT, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    positionals = parsed.positionals
    if len(positionals) != 1:
        print("Error: person name required")
        raise SystemExit(1)
    name = positionals[0]

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

    role = parsed.value(F.FLAG_PEOPLE_ROLE)
    email = parsed.value(F.FLAG_PEOPLE_EMAIL)
    username = parsed.value(F.FLAG_PEOPLE_USERNAME)
    expertise_raw = parsed.value(F.FLAG_PEOPLE_EXPERTISE)
    telegram_user = parsed.value(F.FLAG_PEOPLE_TELEGRAM_USER)
    telegram_id = parsed.value(F.FLAG_PEOPLE_TELEGRAM_ID)

    changed = False
    updated_fields: list[str] = []

    # Edit global entry fields (role, email, username, expertise)
    if role is not None or email is not None or username is not None or expertise_raw is not None:
        global_config = get_global_config()
        for p in global_config.people:
            if p.name == name:
                if role is not None:
                    p.role = role  # type: ignore[assignment]
                    updated_fields.append("role")
                if email is not None:
                    p.email = email
                    updated_fields.append("email")
                if username is not None:
                    p.username = username
                    updated_fields.append("username")
                if expertise_raw is not None:
                    try:
                        p.expertise = json.loads(expertise_raw)
                    except json.JSONDecodeError as e:
                        print(f"Error: --expertise must be valid JSON: {e}")
                        raise SystemExit(1) from e
                    updated_fields.append("expertise")
                changed = True
                break
        if changed:
            save_global_config(global_config)

    # Edit telegram creds
    if telegram_user:
        updated_fields.append("telegram_user")
    if telegram_id:
        updated_fields.append("telegram_id")
    if telegram_user or telegram_id:
        _set_telegram_creds(person.slug or normalize_slug(name), telegram_user, telegram_id)
        changed = True

    if not changed:
        msg = "No changes specified. Use --role, --email, --username, --expertise, --telegram-user, --telegram-id"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}")
        raise SystemExit(1)

    if use_json:
        print(json.dumps({"ok": True, "name": name, "updated": updated_fields}))
    else:
        print(f"Updated {name}: {', '.join(updated_fields)}.")


def _people_remove(args: list[str]) -> None:
    _check_customer_guard()
    parsed = parse_command_args(CONFIG_PEOPLE_REMOVE, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    positionals = parsed.positionals
    if len(positionals) != 1:
        print("Error: person name required")
        raise SystemExit(1)
    name = positionals[0]
    delete_dir = parsed.has(F.FLAG_PEOPLE_DELETE_DIR)

    person = next((p for p in list_people() if p.name == name), None)
    slug = (person.slug if person else None) or normalize_slug(name)

    try:
        remove_person(slug, delete_directory=delete_dir)
    except ValueError as e:
        if use_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}")
        raise SystemExit(1) from e

    if use_json:
        print(json.dumps({"ok": True, "name": name, "directory_deleted": delete_dir}))
    else:
        print(f"Removed {name}.{' Directory deleted.' if delete_dir else ''}")


def _set_telegram_creds(slug: str, user_name: str | None, user_id: str | None) -> None:
    """Set telegram credentials for a person keyed by slug."""
    pc = get_person_config(slug)
    existing = pc.creds.telegram

    tg_user = user_name or (existing.user_name if existing else None)
    tg_id = user_id or (str(existing.user_id) if existing else None)

    if tg_user and tg_id:
        pc.creds.telegram = TelegramCreds(user_name=tg_user, user_id=int(tg_id))
        save_person_config(slug, pc)


# --- Env ---


def _handle_env(args: list[str]) -> None:
    if not args:
        print("Usage: telec config env <list|set> [options]")
        raise SystemExit(1)

    action = args[0]
    rest = args[1:]

    if action == "list":
        parsed = parse_command_args(CONFIG_ENV_LIST, rest)
        _env_list(parsed.has(F.FLAG_JSON_MACHINE_READABLE))
    elif action == "set":
        parsed = parse_command_args(CONFIG_ENV_SET, rest)
        pairs = [token for token in parsed.positionals if "=" in token]
        _env_set(pairs, parsed.has(F.FLAG_JSON_MACHINE_READABLE))
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

    env_file = PROJECT_ENV_PATH
    results = []

    for pair in pairs:
        key, _, value = pair.partition("=")
        if not key or not value:
            continue
        _write_env_var(env_file, key, value)
        os.environ[key] = value  # fmt: skip  # guard: direct-env-read - allowed: environment-file management
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
    parsed = parse_command_args(CONFIG_NOTIFY, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    msg = (
        "Notification toggling has been replaced by per-subscription settings. "
        "Edit subscriptions in person config instead."
    )
    if use_json:
        print(json.dumps({"error": msg}))
    else:
        print(msg)
    raise SystemExit(1)


# --- Validate ---


def _handle_validate(args: list[str]) -> None:
    parsed = parse_command_args(CONFIG_VALIDATE, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)

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
    parsed = parse_command_args(CONFIG_PEOPLE_INVITE, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    positionals = parsed.positionals
    if len(positionals) != 1:
        print("Usage: telec config people invite NAME [--json]")
        raise SystemExit(1)
    name = positionals[0]

    # Verify person exists
    migrate_person_slugs_if_needed()
    people = list_people()
    person = next((p for p in people if p.name == name), None)
    if not person:
        msg = f"Person '{name}' not found"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}")
        raise SystemExit(1)

    # Check for email
    if not person.email:
        msg = f"Person '{name}' has no email address configured"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"Error: {msg}")
        raise SystemExit(1)

    # Run async invite flow
    person_slug = person.slug or normalize_slug(name)
    person_email = person.email

    async def _run_invite() -> InviteResult:
        # Generate/rotate token
        token = set_invite_token(person_slug)

        # Resolve bot usernames/IDs
        telegram_username = None
        discord_bot_id = None

        try:
            telegram_username = await resolve_telegram_bot_username()
        except ValueError as e:
            logger.warning("Failed to resolve Telegram bot username: %s", e)

        try:
            discord_bot_id = await resolve_discord_bot_user_id()
        except ValueError as e:
            logger.warning("Failed to resolve Discord bot user ID: %s", e)

        whatsapp_number = config.whatsapp.business_number

        # Generate links
        links = generate_invite_links(token, telegram_username, discord_bot_id, whatsapp_number)

        # Send email
        try:
            await send_invite_email(name, person_email, links)
            email_sent = True
        except Exception as e:
            logger.warning("Failed to send invite email: %s", e)
            email_sent = False

        return {
            "ok": True,
            "name": name,
            "email": person_email,
            "links": links,
            "email_sent": email_sent,
        }

    result = asyncio.run(_run_invite())

    if use_json:
        print(json.dumps(result))
    else:
        if result["email_sent"]:
            print(f"Invite sent to {person_email} for {name}")
        else:
            available = {platform: url for platform, url in result["links"].items() if url}
            if available:
                relay = "\n".join(f"  {platform}: {url}" for platform, url in available.items())
                print(f"Invite for {name}: email not delivered — share these links directly:\n{relay}")
            else:
                print(f"Invite for {name}: email not delivered and no invite links could be generated.")
