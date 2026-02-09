# Implementation Plan — Config Schema Validation

## Objective

Replace ad-hoc `dict.get()` config reading with validated Pydantic models across all `teleclaude.yml` consumers, enforcing level-specific constraints and fixing the interests schema mismatch.

## Phase 1 — Schema Models

### 1. Create `teleclaude/config/schema.py`

Define Pydantic models for each config level:

```python
class JobScheduleConfig(BaseModel):
    schedule: Literal["hourly", "daily", "weekly", "monthly"] = "daily"
    preferred_hour: int = Field(default=6, ge=0, le=23)
    preferred_weekday: int = Field(default=0, ge=0, le=6)
    preferred_day: int = Field(default=1, ge=1, le=31)

class BusinessConfig(BaseModel):
    domains: dict[str, str] = {}

class GitConfig(BaseModel):
    checkout_root: str | None = None

class PersonEntry(BaseModel):
    name: str
    username: str

class OpsEntry(BaseModel):
    username: str

class TelegramCreds(BaseModel):
    user_name: str
    user_id: int

class CredsConfig(BaseModel):
    telegram: TelegramCreds | None = None

class NotificationsConfig(BaseModel):
    telegram: bool = False

class SubscriptionsConfig(BaseModel):
    youtube: str | None = None

class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    project_name: str | None = None
    business: BusinessConfig = BusinessConfig()
    jobs: dict[str, JobScheduleConfig] = {}
    git: GitConfig = GitConfig()

class GlobalConfig(ProjectConfig):
    people: list[PersonEntry] = []
    ops: list[OpsEntry] = []
    subscriptions: SubscriptionsConfig = SubscriptionsConfig()
    interests: list[str] = []

class PersonConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    creds: CredsConfig = CredsConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    subscriptions: SubscriptionsConfig = SubscriptionsConfig()
    interests: list[str] = []
```

### 2. Create `teleclaude/config/loader.py`

```python
def load_project_config(path: Path) -> ProjectConfig
def load_global_config(path: Path | None = None) -> GlobalConfig
def load_person_config(path: Path) -> PersonConfig
def validate_config(path: Path, level: str) -> BaseModel  # dispatcher
```

Each function: read YAML, validate with Pydantic, return typed model.
Level enforcement via validators (e.g., `PersonConfig` rejects `people` key).

### 3. Tests for Phase 1

- `tests/unit/test_config_schema.py`:
  - Valid project config parses correctly.
  - Valid global config with `people` parses correctly.
  - Valid per-person config with flat `interests` parses correctly.
  - Invalid types rejected (e.g., `preferred_hour: "six"`).
  - Disallowed keys at wrong level (e.g., `people` in per-person) produce errors.
  - Unknown keys produce warnings, not errors.
  - Empty/missing file returns defaults.

## Phase 2 — Consumer Migration

### 4. Migrate `cron/runner.py`

- Replace `_load_job_schedules() -> dict[str, dict[str, str | int]]` with `load_project_config(path).jobs`.
- `_is_due()` takes `JobScheduleConfig` instead of `dict[str, str | int]`.
- Remove manual `int()` casts — Pydantic handles type coercion.

### 5. Migrate `cron/discovery.py`

- Replace `_load_config() -> JsonDict` with `load_global_config()` / `load_person_config()`.
- Access `config.interests` directly (flat `list[str]`), no more `_as_mapping(interests).get("tags")`.
- This fixes the interests schema mismatch bug.

### 6. Migrate `context_selector.py` and `docs_index.py`

- Replace `yaml.safe_load` + `business.get("domains")` with `load_project_config(path).business.domains`.
- Replace `config.get("project_name")` with `config.project_name`.

### 7. Migrate `helpers/git_repo_helper.py`

- Decision: either consolidate to `~/.teleclaude/teleclaude.yml` (standard path) or document the `config/` path.
- Replace ad-hoc YAML loading with `load_global_config()` or a dedicated config path loader.

### 8. Migrate `entrypoints/youtube_sync_subscriptions.py`

- Replace manual config loading with `load_global_config()` / `load_person_config()`.

### 9. Tests for Phase 2

- Existing tests in `test_polling_coordinator.py`, `test_cron_runner.py` etc. should still pass.
- Add integration test: load real `teleclaude.yml` and verify it validates.

## Phase 3 — Level Enforcement

### 10. Add level validators

- `PersonConfig` validator: reject if `people`, `ops`, or `business` keys present.
- `ProjectConfig` validator: reject if `creds`, `notifications`, or `people` keys present.
- These use Pydantic's `model_validator(mode="before")` to inspect raw input.

### 11. Pre-commit guardrail (optional)

- Add a lint check that validates `teleclaude.yml` at project root on commit.
- Validates against `ProjectConfig` schema.

## Files Changed

| File                                                   | Change                                     |
| ------------------------------------------------------ | ------------------------------------------ |
| `teleclaude/config/__init__.py`                        | New package                                |
| `teleclaude/config/schema.py`                          | New — Pydantic models                      |
| `teleclaude/config/loader.py`                          | New — load/validate functions              |
| `teleclaude/cron/runner.py`                            | Migrate to `JobScheduleConfig`             |
| `teleclaude/cron/discovery.py`                         | Migrate to typed config, fix interests bug |
| `teleclaude/context_selector.py`                       | Migrate to `ProjectConfig`                 |
| `teleclaude/docs_index.py`                             | Migrate to `ProjectConfig`                 |
| `teleclaude/helpers/git_repo_helper.py`                | Consolidate config path                    |
| `teleclaude/entrypoints/youtube_sync_subscriptions.py` | Migrate to typed config                    |
| `tests/unit/test_config_schema.py`                     | New — schema validation tests              |

## Risks and Assumptions

1. **Pydantic is already a dependency** — verified in pyproject.toml (via SQLModel).
2. **`extra="allow"`** — unknown keys won't break existing configs during rollout.
3. **YAML parsing unchanged** — `yaml.safe_load` happens inside the loader; Pydantic validates the parsed dict.
4. **No breaking changes** — existing configs all conform to the schema; validation just makes it explicit.
5. **Forward compatibility** — `extra="allow"` lets new keys be added without schema updates (with warning logging).

## Verification

- All 1023+ existing tests pass.
- `scripts/cron_runner.py --list` and `--dry-run` work.
- Real `teleclaude.yml` at all three levels validates without errors.
- Interests tags are correctly populated for per-person subscribers.
