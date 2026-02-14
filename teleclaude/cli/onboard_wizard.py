"""Guided onboarding wizard for TeleClaude first-run setup.

Walks through config areas in order, detects existing state,
and skips completed sections with option to revisit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from teleclaude.cli.config_handlers import (
    add_person,
    check_env_vars,
    discover_config_areas,
    get_person_config,
    list_people,
    save_person_config,
)
from teleclaude.cli.config_menu import (
    _BOLD,
    _DIM,
    _GREEN,
    _RED,
    _RESET,
    _YELLOW,
    _print_header,
    _prompt_confirm,
    _prompt_value,
    _show_adapter_env_vars,
    _show_validation_results,
    _status_icon,
)
from teleclaude.config.schema import PersonEntry


@dataclass
class WizardState:
    """Current onboarding completion state."""

    adapters_complete: bool = False
    people_complete: bool = False
    notifications_complete: bool = False
    env_complete: bool = False


def detect_wizard_state() -> WizardState:
    """Detect which onboarding steps are complete by inspecting config state."""
    state = WizardState()

    areas = discover_config_areas()
    adapter_areas = [a for a in areas if a.category == "adapter"]

    # Adapters: complete if any adapter has config
    state.adapters_complete = any(a.configured for a in adapter_areas)

    # People: complete if at least one person exists
    people = list_people()
    state.people_complete = len(people) > 0

    # Notifications: complete if any person has notification config enabled
    for person in people:
        try:
            pc = get_person_config(person.name)
            if pc.notifications.telegram:
                state.notifications_complete = True
                break
        except Exception:
            continue

    # Env vars: complete if all required vars are set
    env_status = check_env_vars()
    state.env_complete = all(s.is_set for s in env_status) if env_status else True

    return state


def run_onboard_wizard() -> None:
    """Main onboarding wizard entry point."""
    try:
        _wizard_flow()
    except KeyboardInterrupt:
        print(f"\n{_DIM}Onboarding interrupted. Run 'telec onboard' to resume.{_RESET}")


def _wizard_flow() -> None:
    """Inner wizard flow."""
    # Welcome
    _print_header("TeleClaude Onboarding")
    print(f"""
  Welcome to TeleClaude setup! This wizard will walk you through
  configuring your TeleClaude installation step by step.

  {_DIM}You can re-run this wizard at any time with 'telec onboard'.
  Completed sections will be skipped (with option to revisit).{_RESET}
""")

    if not _prompt_confirm("Ready to begin?"):
        print(f"  {_DIM}Run 'telec onboard' when you're ready.{_RESET}")
        return

    state = detect_wizard_state()

    # Step sequence
    steps: list[tuple[str, Callable[[], None], bool]] = [
        ("Platform Selection", _step_platform_selection, state.adapters_complete),
        ("People Management", _step_people, state.people_complete),
        ("Notifications", _step_notifications, state.notifications_complete),
        ("Environment Check", _step_environment, state.env_complete),
        ("Validation", _step_validation, False),  # always run
    ]

    for step_name, step_fn, complete in steps:
        if complete:
            print(f"\n  {_GREEN}\u2713{_RESET} {_BOLD}{step_name}{_RESET} {_DIM}(complete){_RESET}")
            if not _prompt_confirm(f"Revisit {step_name}?", default=False):
                continue
        else:
            print(f"\n  {_YELLOW}\u25b6{_RESET} {_BOLD}{step_name}{_RESET}")

        step_fn()

    # Done
    _print_header("Setup Complete")
    print(f"""
  {_GREEN}TeleClaude is configured!{_RESET}

  {_BOLD}Next steps:{_RESET}
    - Start the daemon: make start
    - Open the TUI:     telec
    - Edit config:      telec config

  {_DIM}Re-run 'telec onboard' anytime to update your setup.{_RESET}
""")


def _step_platform_selection() -> None:
    """Adapter platform selection step."""
    _print_header("Step: Platform Selection")

    areas = discover_config_areas()
    adapter_areas = [a for a in areas if a.category == "adapter"]

    if not adapter_areas:
        print(f"  {_DIM}No adapter platforms available in the current schema.{_RESET}")
        return

    print("\n  Available platforms:")
    for area in adapter_areas:
        icon = _status_icon(area.configured)
        print(f"    {icon} {area.label}")

    print(f"\n  {_DIM}Adapter configuration is done through environment variables.{_RESET}")
    print(f"  {_DIM}Each adapter requires specific env vars to be set.{_RESET}")

    for area in adapter_areas:
        adapter_name = area.name.split(".")[-1]
        if _prompt_confirm(f"\n  View {area.label} setup instructions?", default=not area.configured):
            _show_adapter_env_vars(adapter_name)


def _step_people() -> None:
    """People management step."""
    _print_header("Step: People Management")
    people = list_people()

    if people:
        print(f"\n  {_BOLD}Current people:{_RESET}")
        for p in people:
            print(f"    - {p.name} <{p.email}> ({p.role})")

    if not people or _prompt_confirm("\n  Add a new person?", default=not bool(people)):
        _add_person_wizard()

    # Check for more
    while _prompt_confirm("Add another person?", default=False):
        _add_person_wizard()


def _add_person_wizard() -> None:
    """Guided person addition for wizard."""
    print()
    name = _prompt_value("Name")
    if not name:
        return

    email = _prompt_value("Email")
    if not email:
        return

    print("\n  Available roles: admin, member, contributor, newcomer")
    role = _prompt_value("Role", current="member")
    if role not in ("admin", "member", "contributor", "newcomer"):
        print(f"  {_YELLOW}Invalid role, using 'member'.{_RESET}")
        role = "member"

    try:
        entry = PersonEntry(name=name, email=email, role=role)
        add_person(entry)
        print(f"  {_GREEN}Added '{name}' as {role}.{_RESET}")
    except Exception as e:
        print(f"  {_RED}Error: {e}{_RESET}")


def _step_notifications() -> None:
    """Notification preferences step."""
    _print_header("Step: Notification Preferences")
    people = list_people()

    if not people:
        print(f"  {_DIM}No people configured. Skipping notifications.{_RESET}")
        return

    print(f"\n  {_DIM}Configure which notification channels each person receives.{_RESET}")

    for person in people:
        try:
            pc = get_person_config(person.name)
        except Exception:
            print(f"  {_RED}Could not load config for {person.name}.{_RESET}")
            continue

        tg_icon = _status_icon(pc.notifications.telegram)
        print(f"\n  {_BOLD}{person.name}{_RESET}: telegram {tg_icon}")

        enable = _prompt_confirm(
            f"Enable Telegram notifications for {person.name}?",
            default=pc.notifications.telegram,
        )

        if enable != pc.notifications.telegram:
            pc.notifications.telegram = enable
            try:
                save_person_config(person.name, pc)
                print(f"  {_GREEN}Updated.{_RESET}")
            except Exception as e:
                print(f"  {_RED}Error: {e}{_RESET}")


def _step_environment() -> None:
    """Environment variable check step."""
    _print_header("Step: Environment Check")

    import os

    from teleclaude.cli.config_handlers import get_required_env_vars

    all_vars = get_required_env_vars()

    if not all_vars:
        print(f"  {_DIM}No environment variables required (no adapters configured).{_RESET}")
        return

    missing = []
    for adapter_name, vars_list in sorted(all_vars.items()):
        print(f"\n  {_BOLD}{adapter_name.capitalize()}{_RESET}")
        for var in vars_list:
            is_set = bool(os.environ.get(var.name))
            icon = _status_icon(is_set)
            print(f"    {icon} {var.name}: {var.description}")
            if not is_set:
                missing.append(var)
                print(f"      {_DIM}Example: {var.name}={var.example}{_RESET}")

    if missing:
        print(f"\n  {_YELLOW}Set missing variables before starting the daemon.{_RESET}")
        print(f"  {_DIM}Add them to your .env file or export in your shell.{_RESET}")
    else:
        print(f"\n  {_GREEN}All environment variables are set.{_RESET}")


def _step_validation() -> None:
    """Full validation step."""
    _show_validation_results()
