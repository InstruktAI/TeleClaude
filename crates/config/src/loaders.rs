//! YAML loaders for global, project, and person config overlays.
//!
//! Loaders are pure with respect to the filesystem: they accept a path,
//! return either the parsed overlay (when the file exists) or `None` (when
//! it does not). Hard failures (parse errors, IO errors) surface as
//! [`ConfigError`].
//!
//! The three sources mirror the v1 loader layout:
//!
//! | Scope   | Default path                                          |
//! |---------|--------------------------------------------------------|
//! | Global  | `~/.teleclaude/teleclaude.yml`                         |
//! | Project | `<project_root>/teleclaude.yml`                        |
//! | Person  | `~/.teleclaude/people/<name>/teleclaude.yml`           |
//!
//! Resolution of the effective `Config` from these overlays lives in
//! `effective.rs` (Wave C3); this module's job is to read and parse only.

use std::fs;
use std::path::{Path, PathBuf};

use regex::{Captures, Regex};
use serde_yaml::Value;

use crate::errors::ConfigError;
use crate::models::{GlobalConfig, PersonConfig, ProjectConfig};

const ENV_VAR_TOKEN_PATTERN: &str = r"\$\{([^}]+)\}";

/// Bundle of paths the loader consults to assemble an effective [`Config`].
///
/// The global path is required (single-user MVP has the file at
/// `~/.teleclaude/teleclaude.yml`). The project and person paths are
/// optional and used only when the caller knows the corresponding scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigOverlayPaths {
    pub global: PathBuf,
    pub project: Option<PathBuf>,
    pub person: Option<PathBuf>,
}

/// Result of loading the global YAML file.
pub type GlobalOverlay = GlobalConfig;
/// Result of loading the project YAML file.
pub type ProjectOverlay = ProjectConfig;
/// Result of loading the per-person YAML file.
pub type PersonOverlay = PersonConfig;

/// Load the global overlay from disk.
///
/// Returns [`ConfigError::FileNotFound`] if the path is supplied but
/// absent — the global overlay is structurally required, so missing-file
/// is an error rather than a silent default.
pub fn load_global(path: &Path) -> Result<GlobalOverlay, ConfigError> {
    let raw = read_required(path)?;
    parse_yaml(path, &raw)
}

/// Load the project overlay from disk.
///
/// Returns `Ok(None)` when the path is `None` or the file is absent —
/// project overlays are optional.
pub fn load_project(path: Option<&Path>) -> Result<Option<ProjectOverlay>, ConfigError> {
    let Some(path) = path else {
        return Ok(None);
    };
    let Some(raw) = read_optional(path)? else {
        return Ok(None);
    };
    parse_yaml(path, &raw).map(Some)
}

/// Load the per-person overlay from disk.
///
/// Returns `Ok(None)` when the path is `None` or the file is absent —
/// person overlays are optional.
pub fn load_person(path: Option<&Path>) -> Result<Option<PersonOverlay>, ConfigError> {
    let Some(path) = path else {
        return Ok(None);
    };
    let Some(raw) = read_optional(path)? else {
        return Ok(None);
    };
    parse_yaml(path, &raw).map(Some)
}

fn read_required(path: &Path) -> Result<String, ConfigError> {
    match fs::read_to_string(path) {
        Ok(raw) => Ok(raw),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            Err(ConfigError::FileNotFound(path.to_path_buf()))
        }
        Err(err) => Err(ConfigError::Io(err)),
    }
}

fn read_optional(path: &Path) -> Result<Option<String>, ConfigError> {
    match fs::read_to_string(path) {
        Ok(raw) => Ok(Some(raw)),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(ConfigError::Io(err)),
    }
}

fn parse_yaml<T: serde::de::DeserializeOwned>(path: &Path, raw: &str) -> Result<T, ConfigError> {
    // Treat empty files (which deserialize as YAML null) as default-shaped
    // documents so callers see an empty overlay rather than an opaque
    // "invalid type: unit value" error.
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return serde_yaml::from_str("{}").map_err(|error| ConfigError::ParseFailed {
            file: path.to_path_buf(),
            error: error.to_string(),
        });
    }
    let value: Value = serde_yaml::from_str(raw).map_err(|error| ConfigError::ParseFailed {
        file: path.to_path_buf(),
        error: error.to_string(),
    })?;
    let token_pattern =
        Regex::new(ENV_VAR_TOKEN_PATTERN).map_err(|error| ConfigError::ParseFailed {
            file: path.to_path_buf(),
            error: error.to_string(),
        })?;
    let expanded = expand_env_vars(value, &token_pattern);
    serde_yaml::from_value(expanded).map_err(|error| ConfigError::ParseFailed {
        file: path.to_path_buf(),
        error: error.to_string(),
    })
}

fn expand_env_vars(value: Value, token_pattern: &Regex) -> Value {
    match value {
        Value::Mapping(mapping) => Value::Mapping(
            mapping
                .into_iter()
                .map(|(key, value)| (key, expand_env_vars(value, token_pattern)))
                .collect(),
        ),
        Value::Sequence(sequence) => Value::Sequence(
            sequence
                .into_iter()
                .map(|value| expand_env_vars(value, token_pattern))
                .collect(),
        ),
        Value::String(raw) => Value::String(expand_string_env_vars(&raw, token_pattern)),
        other => other,
    }
}

fn expand_string_env_vars(raw: &str, token_pattern: &Regex) -> String {
    token_pattern
        .replace_all(raw, |captures: &Captures<'_>| {
            let token = captures.get(0).map_or("", |matched| matched.as_str());
            let Some(name) = captures.get(1).map(|matched| matched.as_str()) else {
                return token.to_string();
            };
            match std::env::var(name) {
                Ok(value) => value,
                Err(_) => token.to_string(),
            }
        })
        .into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::fs::write;
    use tempfile::tempdir;

    struct EnvVarGuard {
        name: String,
    }

    impl EnvVarGuard {
        fn set(name: &str, value: &str) -> Self {
            env::set_var(name, value);
            Self {
                name: name.to_string(),
            }
        }

        fn unset(name: impl Into<String>) -> Self {
            let name = name.into();
            env::remove_var(&name);
            Self { name }
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            env::remove_var(&self.name);
        }
    }

    #[test]
    fn load_global_reads_real_world_yaml() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("teleclaude.yml");
        write(
            &path,
            r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
  proficiency: expert
checkout_root: /Users/x/Workspace
"#,
        )
        .expect("write yaml");

        let global = load_global(&path).expect("load global");

        assert_eq!(global.people.len(), 1);
        assert_eq!(global.people[0].name, "Owner");
        assert_eq!(global.checkout_root.as_deref(), Some("/Users/x/Workspace"));
    }

    #[test]
    fn load_global_missing_file_yields_file_not_found() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("absent.yml");

        let err = load_global(&path).expect_err("expected error for absent file");

        assert!(matches!(err, ConfigError::FileNotFound(p) if p == path));
    }

    #[test]
    fn load_project_returns_none_when_path_is_none() {
        let result = load_project(None).expect("none path is Ok(None)");
        assert!(result.is_none());
    }

    #[test]
    fn load_project_returns_none_when_file_absent() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("absent.yml");

        let result = load_project(Some(&path)).expect("absent file is Ok(None)");

        assert!(result.is_none());
    }

    #[test]
    fn load_person_returns_some_when_file_present() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("teleclaude.yml");
        write(
            &path,
            r#"
interests:
- rust
- ai-agents
"#,
        )
        .expect("write yaml");

        let person = load_person(Some(&path))
            .expect("load person")
            .expect("Some person");

        assert_eq!(person.interests, vec!["rust", "ai-agents"]);
    }

    #[test]
    fn empty_file_yields_default_overlay() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("empty.yml");
        write(&path, "").expect("write empty");

        let global = load_global(&path).expect("load empty");

        assert!(global.people.is_empty());
        assert!(global.checkout_root.is_none());
        assert!(global.extra.is_empty());
    }

    #[test]
    fn malformed_yaml_yields_parse_failed() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("bad.yml");
        write(&path, ":\n:\n").expect("write bad yaml");

        let err = load_global(&path).expect_err("expected parse failure");

        assert!(matches!(err, ConfigError::ParseFailed { .. }));
    }

    #[test]
    fn load_project_expands_set_env_var_tokens() {
        const VAR_NAME: &str = "TELEC_TEST_CONFIG_LOADER_SET_TOKEN";
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("teleclaude.yml");
        let _env_var = EnvVarGuard::set(VAR_NAME, "expanded-project");
        write(
            &path,
            format!(
                r#"
project_slug: ${{{VAR_NAME}}}
"#
            ),
        )
        .expect("write yaml");

        let project = load_project(Some(&path))
            .expect("load project")
            .expect("project overlay");

        assert_eq!(project.project_slug.as_deref(), Some("expanded-project"));
    }

    #[test]
    fn load_project_preserves_unset_env_var_tokens() {
        const VAR_NAME: &str = "TELEC_TEST_CONFIG_LOADER_UNSET_TOKEN";
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("teleclaude.yml");
        let _env_var = EnvVarGuard::unset(VAR_NAME);
        write(
            &path,
            format!(
                r#"
project_slug: ${{{VAR_NAME}}}
"#
            ),
        )
        .expect("write yaml");

        let project = load_project(Some(&path))
            .expect("load project")
            .expect("project overlay");

        assert_eq!(
            project.project_slug.as_deref(),
            Some("${TELEC_TEST_CONFIG_LOADER_UNSET_TOKEN}")
        );
    }

    #[test]
    fn load_global_expands_nested_mapping_and_sequence_tokens() {
        const ROOT_VAR: &str = "TELEC_TEST_CONFIG_LOADER_NESTED_ROOT";
        const ITEM_VAR: &str = "TELEC_TEST_CONFIG_LOADER_NESTED_ITEM";
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("teleclaude.yml");
        let _root_env_var = EnvVarGuard::set(ROOT_VAR, "/tmp/telec-root");
        let _item_env_var = EnvVarGuard::set(ITEM_VAR, "ops");
        write(
            &path,
            format!(
                r#"
checkout_root: ${{{ROOT_VAR}}}
interests:
  tags:
    - rust
    - ${{{ITEM_VAR}}}
"#
            ),
        )
        .expect("write yaml");

        let global = load_global(&path).expect("load global");

        assert_eq!(global.checkout_root.as_deref(), Some("/tmp/telec-root"));
        assert_eq!(global.interests, vec!["rust", "ops"]);
    }

    #[test]
    fn load_project_preserves_colon_dash_token_as_literal_when_unset() {
        const VAR_NAME: &str = "TELEC_TEST_CONFIG_LOADER_COLON_DASH";
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("teleclaude.yml");
        let _env_var = EnvVarGuard::unset(format!("{VAR_NAME}:-fallback"));
        write(
            &path,
            format!(
                r#"
project_slug: ${{{VAR_NAME}:-fallback}}
"#
            ),
        )
        .expect("write yaml");

        let project = load_project(Some(&path))
            .expect("load project")
            .expect("project overlay");

        assert_eq!(
            project.project_slug.as_deref(),
            Some("${TELEC_TEST_CONFIG_LOADER_COLON_DASH:-fallback}")
        );
    }
}
