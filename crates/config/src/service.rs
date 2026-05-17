//! ConfigService — overlay-aware effective-config provider.
//!
//! The config service is stateless: it reads three YAML overlays from disk
//! at construction time (or via `reload`) and exposes the effective
//! [`Config`] to callers. There is no Postgres schema for config — see
//! `docs/project/design/architecture-v2/services.md` for the ownership
//! decision.
//!
//! Future versions may emit `config.effective.updated` when reload changes
//! the effective view; today's spine ships read-only, so the event
//! surface is reserved but not yet emitted.

use crate::effective::effective_config;
use crate::errors::ConfigError;
use crate::loaders::{load_global, load_person, load_project, ConfigOverlayPaths};
use crate::models::Config;

/// Stateless config-overlay reader.
///
/// Constructor-injected with the three overlay paths. Each call to
/// [`Self::load`] reads the files fresh and computes the effective
/// [`Config`]; callers that need caching add it at a higher layer.
pub struct ConfigService {
    paths: ConfigOverlayPaths,
}

impl ConfigService {
    /// Build a config service pointed at the given overlay paths.
    ///
    /// The global path is structurally required — see
    /// [`load_global`]. Project and person paths are optional.
    pub fn new(paths: ConfigOverlayPaths) -> Self {
        Self { paths }
    }

    /// Borrow the configured overlay paths (read-only inspection).
    pub fn paths(&self) -> &ConfigOverlayPaths {
        &self.paths
    }

    /// Load the global / project / person overlays and produce the
    /// effective [`Config`].
    ///
    /// Runs [`crate::validate::validate`] on the composed result so
    /// malformed v1 config (unknown role, duplicate roster email,
    /// invalid project slug) fails loudly with
    /// [`ConfigError::ValidationFailed`] or [`ConfigError::MergeConflict`]
    /// rather than riding through into runtime as opaque YAML.
    pub fn load(&self) -> Result<Config, ConfigError> {
        let global = load_global(&self.paths.global)?;
        let project = load_project(self.paths.project.as_deref())?;
        let person = load_person(self.paths.person.as_deref())?;
        let cfg = effective_config(global, project, person);
        crate::validate::validate(&cfg)?;
        Ok(cfg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{create_dir_all, write};
    use tempfile::tempdir;

    fn write_yaml(path: &std::path::Path, contents: &str) {
        if let Some(parent) = path.parent() {
            create_dir_all(parent).expect("mkdir");
        }
        write(path, contents).expect("write yaml");
    }

    #[test]
    fn load_composes_three_overlays_with_person_winning() {
        let dir = tempdir().expect("tempdir");
        let root = dir.path();

        let global_path = root.join("global.yml");
        write_yaml(
            &global_path,
            r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
  proficiency: expert
interests:
- global-interest
"#,
        );

        let project_path = root.join("project.yml");
        write_yaml(
            &project_path,
            r#"
project_slug: teleclaude
language: rust
"#,
        );

        let person_path = root.join("person.yml");
        write_yaml(
            &person_path,
            r#"
interests:
- person-interest
"#,
        );

        let svc = ConfigService::new(ConfigOverlayPaths {
            global: global_path,
            project: Some(project_path),
            person: Some(person_path),
        });

        let cfg = svc.load().expect("load effective config");

        assert_eq!(cfg.global.people.len(), 1);
        assert_eq!(cfg.global.people[0].name, "Owner");
        // person overrides global interests.
        assert_eq!(cfg.global.interests, vec!["person-interest".to_string()]);
        let project = cfg.project.expect("project overlay present");
        assert_eq!(project.project_slug.as_deref(), Some("teleclaude"));
        assert_eq!(project.language.as_deref(), Some("rust"));
    }

    #[test]
    fn load_global_only_yields_config_with_no_overlays() {
        let dir = tempdir().expect("tempdir");
        let global = dir.path().join("global.yml");
        write_yaml(&global, "people: []\n");

        let svc = ConfigService::new(ConfigOverlayPaths {
            global,
            project: None,
            person: None,
        });

        let cfg = svc.load().expect("load global");
        assert!(cfg.project.is_none());
        assert!(cfg.person.is_none());
    }

    #[test]
    fn load_missing_global_surfaces_file_not_found() {
        let dir = tempdir().expect("tempdir");
        let svc = ConfigService::new(ConfigOverlayPaths {
            global: dir.path().join("absent.yml"),
            project: None,
            person: None,
        });
        let err = svc.load().expect_err("expected error");
        assert!(matches!(err, ConfigError::FileNotFound(_)));
    }
}
