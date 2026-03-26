# config-independent-schemas — Input

Config System Redesign: Independent Schemas + Composed AppConfig

## Context

telec docs index crashes from person workspaces because interior functions blindly call load_project_config() on PersonConfig files. The fix: independent schemas, one composed loader, config flows from entry point to consumers.

## Approved Plan (from session b4ea4d35, Mar 22)

### 1. Break GlobalConfig inheritance (config/schema.py)
- GlobalConfig(ProjectConfig) → GlobalConfig(BaseModel) — independent, owns only its fields
- Move checkout_root from GitConfig/ProjectConfig to GlobalConfig (system-wide setting)
- Own reject_disallowed_keys validator blocking project-only and person-only keys

### 2. Add AppConfig (config/schema.py)
- Frozen dataclass: global_: GlobalConfig, project: ProjectConfig | None, person: PersonConfig | None
- Constructed from validated parts, not validated itself

### 3. Add load_app_config(workspace) (config/loader.py)
- Two branches: person workspace (under ~/.teleclaude/people/) or project workspace
- Global always loaded. No fallback for unknown paths.

### 4. Wire docs CLI (cli/telec/handlers/docs.py)
- Call load_app_config(Path.cwd()), pass config to build_context_output()

### 5. Update build_context_output() (context_selector.py)
- Accept config: AppConfig | None parameter
- Read config.project.project_name and config.project.business.domains when project layer exists
- No more interior calls to get_project_name() or _load_project_domains()

### 6. Refactor _load_project_domains → _resolve_domain_paths (context_selector.py)
- Pure path resolution: (domains: dict[str, str], project_root: Path) -> dict[str, Path]
- No config loading

### 7. Update git_repo_helper.py
- Read config.checkout_root directly from GlobalConfig (field moved there)

### 8. Add save_project_config() (config_handlers.py)
- Atomic writes (fcntl + temp + replace), same pattern as global/person
- Route scattered project config writes through it

### 9. Update tests

## Verification
1. cd ~/.teleclaude/people/Maurice\ Faber && telec docs index — returns global snippets, no crash
2. cd /path/to/TeleClaude && telec docs index — works as before
3. telec config validate — all levels pass
4. Pre-commit hooks pass (tests, lint, typecheck)

## Root Cause
PA session runs from ~/.teleclaude/people/Maurice Faber/ where teleclaude.yml is a PersonConfig. telec docs index uses Path.cwd(), resolve_project_config_path finds that file, load_project_config validates it as ProjectConfig which rejects creds and notifications keys.
