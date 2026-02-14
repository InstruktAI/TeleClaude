"""Shared terminal formatting and prompt helpers for interactive CLI flows."""

from __future__ import annotations

import os

from teleclaude.cli.config_handlers import get_required_env_vars, validate_all

_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RESET = "\033[0m"


BOLD = _BOLD
DIM = _DIM
GREEN = _GREEN
RED = _RED
YELLOW = _YELLOW
CYAN = _CYAN
RESET = _RESET


def status_icon(configured: bool) -> str:
    return f"{GREEN}\u2713{RESET}" if configured else f"{RED}\u2717{RESET}"


def print_header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{title}{RESET}")
    print(f"{DIM}{'─' * len(title)}{RESET}")


def prompt_choice(options: list[str], allow_back: bool = True, allow_quit: bool = False) -> str:
    """Display numbered options and return user choice."""
    print()
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    if allow_back:
        print("  b. Back")
    if allow_quit:
        print("  q. Exit")
    print()

    while True:
        try:
            raw = input("Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "q" if allow_quit else "b"

        if raw == "q" and allow_quit:
            return "q"
        if raw == "b" and allow_back:
            return "b"
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return str(idx)
        except ValueError:
            pass
        print(f"  Invalid choice. Enter 1-{len(options)}{', b' if allow_back else ''}{', or q' if allow_quit else ''}.")


def prompt_value(label: str, current: str | None = None, required: bool = True) -> str | None:
    """Prompt user for a value, showing current if set."""
    suffix = f" [{current}]" if current else ""
    req = " (required)" if required and not current else ""

    while True:
        try:
            raw = input(f"  {label}{req}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if not raw and current:
            return current
        if not raw and required:
            print(f"  {RED}Value is required.{RESET}")
            continue
        return raw or None


def prompt_confirm(message: str, default: bool = True) -> bool:
    """Yes/no confirmation prompt."""
    hint = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"  {message} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default

    if not raw:
        return default
    return raw in ("y", "yes")


def show_adapter_env_vars(adapter_name: str) -> None:
    """Show env var details for an adapter."""
    print_header(f"{adapter_name.capitalize()} Environment Variables")
    env_vars = get_required_env_vars().get(adapter_name, [])

    if not env_vars:
        print(f"  {DIM}No environment variables registered.{RESET}")
        input("\n  Press Enter to continue...")
        return

    for var in env_vars:
        is_set = bool(os.environ.get(var.name))
        icon = status_icon(is_set)
        status = "set" if is_set else "NOT SET"
        print(f"\n  {icon} {BOLD}{var.name}{RESET}")
        print(f"    Status: {status}")
        print(f"    Description: {var.description}")
        print(f"    Example: {var.example}")

    print(f"\n  {DIM}Set missing variables in your .env file or shell environment.{RESET}")
    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()


def show_validation_results() -> None:
    """Run and display full validation."""
    print_header("Full Validation")
    print(f"  {DIM}Running validation...{RESET}")

    results = validate_all()

    all_passed = True
    for r in results:
        icon = status_icon(r.passed)
        print(f"\n  {icon} {BOLD}{r.area}{RESET}")
        if not r.passed:
            all_passed = False
            for err in r.errors:
                print(f"    {RED}Error: {err}{RESET}")
            for sug in r.suggestions:
                print(f"    {YELLOW}Fix: {sug}{RESET}")

    if all_passed:
        print(f"\n  {GREEN}All checks passed.{RESET}")
    else:
        print(f"\n  {RED}Some checks failed. See above for details.{RESET}")

    try:
        input("\n  Press Enter to continue...")
    except (EOFError, KeyboardInterrupt):
        print()
