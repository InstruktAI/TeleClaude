---
id: 'project/design/architecture/feature-flags'
type: 'design'
scope: 'project'
description: 'Design of the experiment and feature-flag system for safe feature toggling.'
---

# Feature Flags — Design

## Purpose

To allow safe deployment of new features by toggling them on or off without code changes. The system supports targeting specific AI agents (e.g., enabling a feature only for `gemini` while keeping it off for `claude`) or enabling it globally. This facilitates A/B testing, gradual rollouts, and "experiment" management.

## Inputs/Outputs

**Inputs:**

1. **`experiments.yml`**: An optional YAML file in the project root containing a list of active experiments.
2. **`config.yml`**: The main configuration file which can also contain an `experiments` list (merged with `experiments.yml`).
3. **`config.is_experiment_enabled(name, agent)`**: The API called by application code to check feature status.

**Outputs:**

- **Boolean Status**: `True` if the feature is enabled for the requested context, `False` otherwise.

## See Also

- docs/project/policy/feature-flag-usage.md — Rules for when to use (and not use) feature flags

## Invariants

- **Default Safe**: Experiments are disabled by default if not explicitly listed.
- **Scope Specificity**: An experiment can apply to all agents (if `agents` list is missing/empty) or a specific subset.
- **Configuration Precedence**: `experiments.yml` is loaded alongside `config.yml`, and its entries are merged into the runtime configuration.
- **Runtime Immutability**: Experiment states are loaded at startup and do not change until the application is restarted.

## Primary flows

### 1. Configuration Loading

1. The daemon starts and loads `config.yml`.
2. It checks for the existence of `experiments.yml` in the same directory.
3. If found, `experiments.yml` is parsed and its `experiments` list is appended to the `experiments` list from `config.yml`.
4. The combined list is stored in the global `config` object.

### 2. Feature Check

1. Application code calls `config.is_experiment_enabled("my_feature", agent="gemini")`.
2. The method iterates through the loaded experiments.
3. It checks for a name match (`my_feature`).
4. If matched, it checks the agent constraint:
   - If the experiment has no `agents` list, it returns `True` (global).
   - If the experiment has an `agents` list and "gemini" is in it, it returns `True`.
   - Otherwise, it continues searching.
5. If no matching enabled experiment is found, it returns `False`.

## Failure modes

- **Missing `experiments.yml`**: The system proceeds normally using only `config.yml` (or no experiments).
- **Invalid YAML**: The application will fail to start (standard configuration loading behavior).
- **Undefined Agent**: If code queries for an agent not present in the configuration, the check simply returns `False` (unless the experiment is global).
