"""Interactive configuration menu for TeleClaude.

Simple stdin/stdout prompt-based interface for browsing and editing
user configs. No curses dependency — works in any terminal.
"""

from __future__ import annotations

import os

from pydantic import ValidationError

from teleclaude.cli.config_handlers import (
    ConfigArea,
    add_person,
    check_env_vars,
    discover_config_areas,
    get_person_config,
    get_required_env_vars,
    list_people,
    save_person_config,
)
from teleclaude.cli.prompt_utils import (
    BOLD as _BOLD,
)
from teleclaude.cli.prompt_utils import (
    DIM as _DIM,
)
from teleclaude.cli.prompt_utils import (
    GREEN as _GREEN,
)
from teleclaude.cli.prompt_utils import (
    RED as _RED,
)
from teleclaude.cli.prompt_utils import (
    RESET as _RESET,
)
from teleclaude.cli.prompt_utils import (
    YELLOW as _YELLOW,
)
from teleclaude.cli.prompt_utils import (
    print_header as _print_header,
)
from teleclaude.cli.prompt_utils import (
    prompt_choice as _prompt_choice,
)
from teleclaude.cli.prompt_utils import (
    prompt_confirm as _prompt_confirm,
)
from teleclaude.cli.prompt_utils import (
    prompt_value as _prompt_value,
)
from teleclaude.cli.prompt_utils import (
    show_adapter_env_vars as _show_adapter_env_vars,
)
from teleclaude.cli.prompt_utils import (
    show_validation_results as _show_validation_results,
)
from teleclaude.cli.prompt_utils import (
    status_icon as _status_icon,
)
from teleclaude.config.schema import PersonConfig, PersonEntry

# --- Menu screens ---


def run_interactive_menu() -> None:
    """Main interactive config menu loop."""
    try:
        _main_menu_loop()
    except KeyboardInterrupt:
        print(f"\n{_DIM}Exiting configuration.{_RESET}")


def _main_menu_loop() -> None:
    """Inner loop for main menu."""
    while True:
        areas = discover_config_areas()
        _print_header("TeleClaude Configuration")

        adapter_areas = [a for a in areas if a.category == "adapter"]
        notif_area = next((a for a in areas if a.category == "notifications"), None)

        options = []

        # Adapters
        adapter_count = sum(1 for a in adapter_areas if a.configured)
        adapter_status = f"  {_DIM}({adapter_count}/{len(adapter_areas)} configured){_RESET}" if adapter_areas else ""
        options.append(f"Adapters{adapter_status}")

        # People
        people = list_people()
        people_status = f"  {_DIM}({len(people)} configured){_RESET}" if people else ""
        options.append(f"People{people_status}")

        # Notifications
        notif_icon = _status_icon(notif_area.configured) if notif_area else ""
        options.append(f"Notifications  {notif_icon}")

        # Environment
        env_statuses = check_env_vars()
        missing_count = sum(1 for s in env_statuses if not s.is_set)
        env_suffix = f"  {_YELLOW}{missing_count} missing vars{_RESET}" if missing_count else ""
        options.append(f"Environment{env_suffix}")

        # Validate all
        options.append("Validate all")

        choice = _prompt_choice(options, allow_back=False, allow_quit=True)

        if choice == "q":
            return
        elif choice == "1":
            _show_adapter_menu(adapter_areas)
        elif choice == "2":
            _show_people_menu()
        elif choice == "3":
            _show_notifications_menu()
        elif choice == "4":
            _show_environment_menu()
        elif choice == "5":
            _show_validation_results()


def _show_adapter_menu(adapter_areas: list[ConfigArea]) -> None:
    """Submenu for adapter configuration."""
    while True:
        _print_header("Adapters")
        options = [f"{a.label}  {_status_icon(a.configured)}" for a in adapter_areas]
        choice = _prompt_choice(options)

        if choice == "b":
            return

        try:
            idx = int(choice) - 1
            area = adapter_areas[idx]
            _show_adapter_detail(area)
        except (ValueError, IndexError):
            continue


def _show_adapter_detail(area: ConfigArea) -> None:
    """Show adapter config detail and options."""
    while True:
        _print_header(f"{area.label} Configuration")

        # Show env vars for this adapter
        adapter_name = area.name.split(".")[-1]
        env_vars = get_required_env_vars().get(adapter_name, [])

        if env_vars:
            print(f"\n  {_BOLD}Environment variables:{_RESET}")
            for var in env_vars:
                is_set = bool(os.environ.get(var.name))
                icon = _status_icon(is_set)
                print(f"    {icon} {var.name}: {var.description}")
        else:
            print(f"\n  {_DIM}No environment variables registered for this adapter.{_RESET}")

        options = [
            "Show required environment variables",
        ]
        choice = _prompt_choice(options)

        if choice == "b":
            return
        elif choice == "1":
            _show_adapter_env_vars(adapter_name)


def _show_people_menu() -> None:
    """Submenu for people management."""
    while True:
        _print_header("People Management")
        people = list_people()

        if people:
            print(f"\n  {_BOLD}Configured people:{_RESET}")
            for p in people:
                print(f"    - {p.name} <{p.email}> ({p.role})")
        else:
            print(f"\n  {_DIM}No people configured yet.{_RESET}")

        options = ["Add person", "Edit person", "List people details"]
        choice = _prompt_choice(options)

        if choice == "b":
            return
        elif choice == "1":
            _add_person_flow()
        elif choice == "2":
            _edit_person_flow()
        elif choice == "3":
            _list_people_detail()


def _add_person_flow() -> None:
    """Guided flow to add a new person."""
    _print_header("Add Person")

    name = _prompt_value("Name")
    if not name:
        return

    email = _prompt_value("Email")
    if not email:
        return

    print("\n  Roles: admin, member, contributor, newcomer")
    role = _prompt_value("Role", current="member")
    if role not in ("admin", "member", "contributor", "newcomer"):
        print(f"  {_RED}Invalid role. Using 'member'.{_RESET}")
        role = "member"

    try:
        entry = PersonEntry(name=name, email=email, role=role)
        add_person(entry)
        print(f"\n  {_GREEN}Added person '{name}' as {role}.{_RESET}")
    except ValueError as e:
        print(f"\n  {_RED}Error: {e}{_RESET}")

    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()


def _edit_person_flow() -> None:
    """Edit an existing person's config."""
    people = list_people()
    if not people:
        print(f"\n  {_DIM}No people to edit.{_RESET}")
        try:
            input("\n  Press Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            print()
        return

    _print_header("Edit Person")
    options = [f"{p.name} <{p.email}> ({p.role})" for p in people]
    choice = _prompt_choice(options)

    if choice == "b":
        return

    try:
        idx = int(choice) - 1
        person = people[idx]
    except (ValueError, IndexError):
        return

    _edit_person_detail(person)


def _edit_person_detail(person: PersonEntry) -> None:
    """Edit a specific person's per-person config."""
    _print_header(f"Edit: {person.name}")

    try:
        pc = get_person_config(person.name)
    except (ValueError, ValidationError) as e:
        print(f"  {_RED}Error loading config: {e}{_RESET}")
        try:
            input("\n  Press Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            print()
        return

    # Show current state
    if pc.creds.telegram:
        print(f"  Telegram: {_GREEN}configured{_RESET} (user: {pc.creds.telegram.user_name})")
    else:
        print(f"  Telegram: {_DIM}not configured{_RESET}")

    print(f"  Notifications: telegram={pc.notifications.telegram}")
    print(f"  Interests: {', '.join(pc.interests) if pc.interests else 'none'}")

    options = ["Edit notifications", "Edit interests"]
    choice = _prompt_choice(options)

    if choice == "b":
        return
    elif choice == "1":
        _edit_notifications_for_person(person.name, pc)
    elif choice == "2":
        _edit_interests_for_person(person.name, pc)


def _edit_notifications_for_person(name: str, pc: PersonConfig) -> None:
    """Edit notification preferences for a person."""
    _print_header(f"Notifications: {name}")
    print(f"  Current: telegram={pc.notifications.telegram}")

    enable = _prompt_confirm("Enable Telegram notifications?", default=pc.notifications.telegram)
    pc.notifications.telegram = enable

    try:
        save_person_config(name, pc)
        print(f"\n  {_GREEN}Notifications updated.{_RESET}")
    except (ValueError, OSError) as e:
        print(f"\n  {_RED}Error: {e}{_RESET}")

    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()


def _edit_interests_for_person(name: str, pc: PersonConfig) -> None:
    """Edit interests for a person."""
    _print_header(f"Interests: {name}")
    print(f"  Current: {', '.join(pc.interests) if pc.interests else 'none'}")

    raw = _prompt_value("Interests (comma-separated)", current=", ".join(pc.interests), required=False)
    if raw is not None:
        pc.interests = [i.strip() for i in raw.split(",") if i.strip()]
        try:
            save_person_config(name, pc)
            print(f"\n  {_GREEN}Interests updated.{_RESET}")
        except (ValueError, OSError) as e:
            print(f"\n  {_RED}Error: {e}{_RESET}")

    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()


def _list_people_detail() -> None:
    """Show detailed info for all people."""
    _print_header("People Details")
    people = list_people()

    if not people:
        print(f"  {_DIM}No people configured.{_RESET}")
    else:
        for person in people:
            print(f"\n  {_BOLD}{person.name}{_RESET}")
            print(f"    Email: {person.email}")
            print(f"    Role:  {person.role}")
            try:
                pc = get_person_config(person.name)
                has_tg = pc.creds.telegram is not None
                print(f"    Telegram creds: {'yes' if has_tg else 'no'}")
                print(f"    Notifications: telegram={pc.notifications.telegram}")
            except (ValueError, ValidationError):
                print(f"    {_DIM}(config not loaded){_RESET}")

    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()


def _show_notifications_menu() -> None:
    """Submenu for notification subscriptions."""
    while True:
        _print_header("Notification Subscriptions")
        people = list_people()

        if not people:
            print(f"  {_DIM}No people configured. Add people first.{_RESET}")
            try:
                input("\n  Press Enter to continue...")
            except (EOFError, KeyboardInterrupt):
                print()
            return

        for person in people:
            try:
                pc = get_person_config(person.name)
                tg_icon = _status_icon(pc.notifications.telegram)
                print(f"  {person.name}: telegram {tg_icon}")
            except (ValueError, ValidationError):
                print(f"  {person.name}: {_DIM}(config error){_RESET}")

        options = [f"Edit {p.name}'s notifications" for p in people]
        choice = _prompt_choice(options)

        if choice == "b":
            return

        try:
            idx = int(choice) - 1
            person = people[idx]
            pc = get_person_config(person.name)
            _edit_notifications_for_person(person.name, pc)
        except (ValueError, IndexError, ValidationError):
            continue


def _show_environment_menu() -> None:
    """Show environment variable status and examples."""
    _print_header("Environment Variables")

    all_vars = get_required_env_vars()

    if not all_vars:
        print(f"  {_DIM}No adapters configured — no environment variables required.{_RESET}")
        try:
            input("\n  Press Enter to continue...")
        except (EOFError, KeyboardInterrupt):
            print()
        return

    missing_any = False
    for adapter_name, vars_list in sorted(all_vars.items()):
        print(f"\n  {_BOLD}{adapter_name.capitalize()}{_RESET}")
        for var in vars_list:
            is_set = bool(os.environ.get(var.name))
            icon = _status_icon(is_set)
            print(f"    {icon} {var.name}")
            if not is_set:
                missing_any = True
                print(f"      {_DIM}Example: {var.name}={var.example}{_RESET}")

    if missing_any:
        print(f"\n  {_YELLOW}Add missing variables to your .env or shell environment.{_RESET}")
    else:
        print(f"\n  {_GREEN}All required environment variables are set.{_RESET}")

    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()
