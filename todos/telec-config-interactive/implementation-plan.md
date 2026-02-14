# Implementation Plan: Interactive Configuration System

## Architecture Overview

Three layers, bottom-up:

1. **Config handlers** — read/write/validate user configs (global + per-person YAML)
2. **Interactive menu** — curses-free stdin/stdout prompts for browsing and editing config
3. **Onboarding wizard** — sequential guided setup reusing config handlers

All three layers share the same read/write foundation. The interactive menu and wizard
are thin wrappers over the config handlers — they don't duplicate validation or I/O logic.

**Key distinction:** The delivered `config_cmd.py` handles the daemon's `config.yml`
(runtime config). This todo handles _user-facing_ config: `~/.teleclaude/teleclaude.yml`
(global) and `~/.teleclaude/people/{name}/teleclaude.yml` (per-person). Different schemas,
different files, same atomic write discipline.

## Dependency Map

```
Task 1: Config Handlers  ←  foundation, no deps
Task 2: CLI Integration   ←  depends on Task 1
Task 3: Interactive Menu   ←  depends on Task 1
Task 4: Onboarding Wizard  ←  depends on Task 1 + Task 3 (reuses menu rendering)
Task 5: Tests              ←  depends on Task 1-4
```

## Task 1: Config Handler Layer

**File:** `teleclaude/cli/config_handlers.py`

**Purpose:** Provide read/write/validate operations for user configs that the menu
and wizard both consume. This is the shared config layer referenced in FR9.

### Functions to implement

```python
# --- Reading ---
def get_global_config() -> GlobalConfig:
    """Load ~/.teleclaude/teleclaude.yml as GlobalConfig."""

def get_person_config(name: str) -> PersonConfig:
    """Load ~/.teleclaude/people/{name}/teleclaude.yml as PersonConfig."""

def list_people() -> list[PersonEntry]:
    """Return all people from global config."""

def list_person_dirs() -> list[str]:
    """Scan ~/.teleclaude/people/ for person directories."""

# --- Writing (atomic) ---
def save_global_config(config: GlobalConfig) -> None:
    """Atomic write of global config. Uses ruamel.yaml to preserve comments."""

def save_person_config(name: str, config: PersonConfig) -> None:
    """Atomic write of per-person config. Creates directory if needed."""

def add_person(entry: PersonEntry) -> None:
    """Add person to global people list + create per-person directory."""

def remove_person(name: str) -> None:
    """Remove person from global list + optionally remove directory."""

# --- Validation ---
def validate_all() -> list[ValidationResult]:
    """Run full-system validation: schema + cross-reference + env vars."""

# --- Environment ---
def get_required_env_vars() -> dict[str, EnvVarInfo]:
    """Aggregate required env vars across configured adapters."""

def check_env_vars() -> list[EnvVarStatus]:
    """Check which required env vars are set."""

# --- Schema discovery ---
def discover_config_areas() -> list[ConfigArea]:
    """Inspect schema models to find available config areas."""
```

### Data classes

```python
@dataclass
class ConfigArea:
    name: str           # e.g. "adapters.telegram"
    label: str          # e.g. "Telegram"
    category: str       # "adapter" | "people" | "notifications" | "environment"
    configured: bool    # status indicator
    model_class: type   # Pydantic model for this area

@dataclass
class EnvVarInfo:
    name: str           # e.g. "TELEGRAM_BOT_TOKEN"
    adapter: str        # which adapter needs it
    description: str
    example: str        # example value for .env

@dataclass
class EnvVarStatus:
    info: EnvVarInfo
    is_set: bool

@dataclass
class ValidationResult:
    area: str
    passed: bool
    errors: list[str]
    suggestions: list[str]
```

### Schema-driven discovery (FR8)

Adapter config models are discovered by inspecting `CredsConfig` fields and adapter-
specific models in `teleclaude/config/schema.py`. Today only `TelegramCreds` exists.
When `role-based-notifications` adds `DiscordCreds` / `WhatsAppCreds`, they appear
automatically via field introspection on `CredsConfig`.

Adapter env var requirements are defined in a registry dict keyed by adapter name:

```python
_ADAPTER_ENV_VARS: dict[str, list[EnvVarInfo]] = {
    "telegram": [
        EnvVarInfo("TELEGRAM_BOT_TOKEN", "telegram", "Telegram Bot API token", "123456:ABC-DEF..."),
    ],
    # Future adapters add entries here or via a registration function
}
```

This is a minimal registry — not hardcoded menu entries. When a new adapter schema
model appears but has no env var entry, the menu still shows it; it just can't check
env vars for that adapter.

### Atomic write pattern

Reuse the proven pattern from `teleclaude/cli/tui/state_store.py`:

1. Write to `.tmp` file
2. `f.flush()` + `os.fsync()`
3. `os.replace()` (atomic on POSIX)
4. File locking with `fcntl` (best-effort)

Use `ruamel.yaml` (already in `pyproject.toml`) for format-preserving YAML writes.
Load with `ruamel.yaml` round-trip mode to preserve comments and ordering, then
validate the data dict with Pydantic before writing.

### Verification

- Unit tests for each handler function
- Round-trip test: load → modify → save → reload → assert equal
- Atomic write test: verify `.tmp` is cleaned up, verify no partial writes on exception

---

## Task 2: CLI Integration

**Files:** `teleclaude/cli/telec.py`, `teleclaude/cli/config_cmd.py`

### Changes to `telec.py`

1. Add `CONFIG = "config"` and `ONBOARD = "onboard"` to `TelecCommand` enum.
2. Add `_handle_config(args)` handler:
   - No args → launch interactive menu (Task 3)
   - `get` / `patch` / `validate` → delegate to existing `config_cmd.handle_config_command()`
   - `--help` → print usage
3. Add `_handle_onboard(args)` handler → launch wizard (Task 4).
4. Add completion entries for both commands.
5. Update `_usage()` help text.

### Changes to `config_cmd.py`

Restore source file from git history (only `.pyc` exists currently). The existing
`get/patch/validate` implementation targets the daemon `config.yml`. This remains
unchanged — the interactive system is a separate code path for user configs.

### Makefile

Add `onboard` target:

```makefile
onboard:
	@telec onboard
```

### Verification

- `telec config --help` shows usage
- `telec config` (no args) enters interactive mode
- `telec config get/patch/validate` still works (backward compatible)
- `telec onboard` enters wizard
- `make onboard` works

---

## Task 3: Interactive Menu

**File:** `teleclaude/cli/config_menu.py`

**Approach:** Simple stdin/stdout menu using `input()` and ANSI escape codes for
formatting. Not curses-based — the TUI is for the main dashboard; config editing
benefits from a simpler prompt-based interface where users type values naturally.

### Menu structure

```
TeleClaude Configuration

  1. Adapters
  2. People                (1 configured)
  3. Notifications
  4. Environment           2 missing vars
  5. Validate all
  q. Exit

Choice:
```

Drilling into "Adapters":

```
Adapters

  1. Telegram              ✓ configured
  2. Discord               ✗ not configured
  3. WhatsApp              ✗ not configured
  b. Back

Choice:
```

Drilling into "Telegram":

```
Telegram Configuration

  Current values:
    bot_token: ✓ set (env: TELEGRAM_BOT_TOKEN)

  1. View current config
  2. Show required environment variables
  b. Back

Choice:
```

### Implementation

```python
def run_interactive_menu() -> None:
    """Main interactive config menu loop."""
    areas = discover_config_areas()
    while True:
        choice = show_main_menu(areas)
        if choice == "q":
            break
        handle_menu_choice(choice, areas)

def show_main_menu(areas: list[ConfigArea]) -> str:
    """Display main menu and return user choice."""

def show_adapter_menu(adapter_areas: list[ConfigArea]) -> None:
    """Submenu for adapter configuration."""

def show_people_menu() -> None:
    """Submenu for people management: list, add, edit."""

def show_notifications_menu() -> None:
    """Submenu for notification subscriptions."""

def show_environment_menu() -> None:
    """Show env var status and examples."""

def show_validation_results() -> None:
    """Run and display full validation."""
```

### Formatting helpers

```python
def status_indicator(configured: bool) -> str:
    """Return ✓/✗ status string."""

def print_header(title: str) -> None:
    """Print formatted section header."""

def prompt_value(label: str, current: str | None = None, required: bool = True) -> str:
    """Prompt user for a value, showing current if set."""

def prompt_choice(options: list[str], allow_back: bool = True) -> str:
    """Display numbered options and return choice."""

def prompt_confirm(message: str, default: bool = True) -> bool:
    """Yes/no confirmation prompt."""
```

### Ctrl+C safety

Wrap all write operations in try/except. The config handlers (Task 1) handle
atomic writes. The menu catches `KeyboardInterrupt` at the top level and exits
gracefully with a message. No partial state is possible because each write is
atomic (write to tmp, then replace).

### Verification

- Navigate all menu levels
- Edit a config value and verify file updated correctly
- Ctrl+C at any point leaves config unchanged
- Status indicators reflect actual config state

---

## Task 4: Onboarding Wizard

**File:** `teleclaude/cli/onboard_wizard.py`

### Step sequence

1. **Welcome** — explain what the wizard does
2. **Platform selection** — which adapters to enable (checkboxes)
3. **Adapter setup** — for each selected adapter, configure it (reuse adapter menu from Task 3)
4. **People management** — add first person (usually self as admin)
5. **Notification preferences** — set channels and preferred platform per person
6. **Environment check** — show missing vars with examples
7. **Full validation** — run validation and show results
8. **Done** — summary of what was configured

### State detection (FR2)

```python
def detect_wizard_state() -> WizardState:
    """Detect which steps are complete by inspecting config state."""
    # Step 1 (adapters): complete if any adapter has config
    # Step 2 (people): complete if at least one person exists
    # Step 3 (notifications): complete if any person has notification config
    # Step 4 (env vars): complete if all required vars are set
```

Re-running the wizard skips completed steps but offers `[r] Revisit this section`.

### Documentation links

Each step includes a help option that prints relevant doc links. These are
hardcoded strings per adapter — they come from the adapter todos' documentation
deliverables. For adapters that haven't shipped yet, the help text says
"Documentation will be available when this adapter is configured."

### Implementation

```python
def run_onboard_wizard() -> None:
    """Main onboarding wizard."""
    state = detect_wizard_state()
    steps = [
        ("Platform Selection", run_platform_step, state.adapters_complete),
        ("Adapter Setup", run_adapter_step, state.adapters_configured),
        ("People Management", run_people_step, state.people_complete),
        ("Notifications", run_notifications_step, state.notifications_complete),
        ("Environment Check", run_env_step, state.env_complete),
        ("Validation", run_validation_step, False),  # always run
    ]

    for name, step_fn, complete in steps:
        if complete:
            if not prompt_confirm(f"{name} is complete. Revisit?", default=False):
                continue
        step_fn()
```

### Verification

- `telec onboard` walks through all steps in order
- Completed sections are skipped (with option to revisit)
- Re-running onboard detects existing config
- Each step's writes are validated immediately

---

## Task 5: Tests

**File:** `tests/unit/test_config_interactive.py`

### Test coverage

1. **Config handlers:**
   - `test_get_global_config_loads_correctly`
   - `test_get_person_config_loads_correctly`
   - `test_save_global_config_atomic_write`
   - `test_save_person_config_creates_directory`
   - `test_add_person_adds_to_global_and_creates_dir`
   - `test_validate_all_catches_invalid_config`
   - `test_discover_config_areas_reflects_schema`
   - `test_check_env_vars_detects_missing`
   - `test_atomic_write_cleans_up_on_failure`

2. **CLI integration:**
   - `test_telec_config_no_args_launches_interactive`
   - `test_telec_onboard_launches_wizard`
   - `test_telec_config_get_still_works`

3. **Menu rendering (output capture):**
   - `test_main_menu_shows_all_areas`
   - `test_status_indicator_shows_configured`
   - `test_people_menu_lists_people`

### Test approach

- Use `tmp_path` fixtures for config files
- Monkeypatch `input()` for menu interaction tests
- Use `capsys` for output capture verification
- No daemon or network dependencies

---

## File Summary

| File                                    | Action  | Purpose                                 |
| --------------------------------------- | ------- | --------------------------------------- |
| `teleclaude/cli/config_handlers.py`     | CREATE  | Shared config read/write/validate layer |
| `teleclaude/cli/config_menu.py`         | CREATE  | Interactive menu implementation         |
| `teleclaude/cli/onboard_wizard.py`      | CREATE  | Guided onboarding wizard                |
| `teleclaude/cli/telec.py`               | EDIT    | Add CONFIG + ONBOARD commands           |
| `teleclaude/cli/config_cmd.py`          | RESTORE | Restore source from git history         |
| `Makefile`                              | EDIT    | Add `onboard` target                    |
| `tests/unit/test_config_interactive.py` | CREATE  | Unit tests                              |

## Risks and Mitigations

| Risk                                              | Mitigation                                                             |
| ------------------------------------------------- | ---------------------------------------------------------------------- |
| Scope creep from adapter todos not yet landed     | Ship with existing schema models only; new ones appear automatically   |
| ruamel.yaml comment preservation complexity       | Test round-trip carefully; fall back to pyyaml if ruamel causes issues |
| stdin/stdout menu UX in non-interactive terminals | Detect `sys.stdin.isatty()` and fail fast with helpful message         |
| Config file corruption on concurrent writes       | Atomic writes + file locking (existing pattern)                        |

## Build Sequence

- [x] Config handlers → commit
- [x] CLI integration + restore config_cmd.py → commit
- [x] Interactive menu → commit
- [x] Onboarding wizard → commit
- [x] Tests → commit
- [x] Final validation pass → done
