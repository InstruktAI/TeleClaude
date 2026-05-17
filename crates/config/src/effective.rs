//! Effective-config computation.
//!
//! Combines the three overlay sources (global, project, person) into one
//! effective [`Config`] applying v1's overlay precedence:
//!
//! > **person > project > global**
//!
//! That is: a per-person value wins over a project value, which wins over
//! a global value. Fields where only one overlay carries content surface
//! that value unchanged.
//!
//! This module is pure. Loading from disk lives in `loaders.rs`; this code
//! takes the parsed overlays and merges them deterministically.

use serde_yaml::{Mapping, Value};

use crate::models::{Config, GlobalConfig, PersonConfig, PersonEntry, ProjectConfig};

/// Compute the effective [`Config`] from the three overlays.
///
/// The result's `global` is the merged global view (people / interests /
/// checkout_root / extra) with person overrides applied where defined;
/// `project` and `person` are echoed through verbatim for callers that
/// need to inspect the raw overlay sources.
///
/// Overlay precedence (`person > project > global`):
///
/// | Field                              | Sourced from                                    |
/// |------------------------------------|-------------------------------------------------|
/// | `interests`                        | person if non-empty else project? else global   |
/// | `checkout_root`                    | global only (no person/project knob in v1)      |
/// | `people`                           | global only — roster lives at the global level  |
/// | extra (top-level unknowns)         | merged: person → project → global               |
///
/// Project's `interests`/`extra` is merged into the same precedence stack
/// when the project overlay defines them.
pub fn effective_config(
    global: GlobalConfig,
    project: Option<ProjectConfig>,
    person: Option<PersonConfig>,
) -> Config {
    let mut merged_global = global.clone();

    // interests: first non-empty across person > project > global. An empty
    // person overlay must not stop a non-empty project overlay from taking
    // effect — the precedence is "the next level inheriting non-empty
    // content," not "the highest level that exists at all."
    let person_interests = person
        .as_ref()
        .map(|p| p.interests.clone())
        .unwrap_or_default();
    let project_interests = project
        .as_ref()
        .map(|p| project_extra_string_list(&p.extra, "interests"))
        .unwrap_or_default();
    if !person_interests.is_empty() {
        merged_global.interests = person_interests;
    } else if !project_interests.is_empty() {
        merged_global.interests = project_interests;
    }

    // extra: shallow merge with person > project > global.
    let mut merged_extra = global.extra;
    if let Some(proj) = project.as_ref() {
        overlay_mapping(&mut merged_extra, &proj.extra);
    }
    if let Some(p) = person.as_ref() {
        overlay_mapping(&mut merged_extra, &p.extra);
    }
    merged_global.extra = merged_extra;

    Config {
        global: merged_global,
        project,
        person,
    }
}

/// Look up the person roster entry whose email matches `email` (case-
/// sensitive — v1 stores email verbatim).
pub fn find_person_entry<'a>(config: &'a Config, email: &str) -> Option<&'a PersonEntry> {
    config.global.people.iter().find(|p| p.email == email)
}

fn overlay_mapping(base: &mut Mapping, overlay: &Mapping) {
    for (k, v) in overlay {
        base.insert(k.clone(), v.clone());
    }
}

fn project_extra_string_list(extra: &Mapping, key: &str) -> Vec<String> {
    extra
        .get(Value::String(key.to_string()))
        .and_then(|v| v.as_sequence())
        .map(|seq| {
            seq.iter()
                .filter_map(|item| item.as_str().map(str::to_owned))
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_yaml::Value;

    fn yv(s: &str) -> Value {
        Value::String(s.into())
    }

    #[test]
    fn person_interests_override_global_interests() {
        let global = GlobalConfig {
            interests: vec!["global-1".into(), "global-2".into()],
            ..GlobalConfig::default()
        };
        let person = PersonConfig {
            interests: vec!["person-1".into()],
            ..PersonConfig::default()
        };
        let cfg = effective_config(global, None, Some(person));
        assert_eq!(cfg.global.interests, vec!["person-1".to_string()]);
    }

    #[test]
    fn project_interests_apply_when_person_is_absent() {
        let global = GlobalConfig {
            interests: vec!["global-1".into()],
            ..GlobalConfig::default()
        };
        let mut project_extra = Mapping::new();
        project_extra.insert(
            yv("interests"),
            Value::Sequence(vec![yv("project-1"), yv("project-2")]),
        );
        let project = ProjectConfig {
            extra: project_extra,
            ..ProjectConfig::default()
        };

        let cfg = effective_config(global, Some(project), None);

        assert_eq!(
            cfg.global.interests,
            vec!["project-1".to_string(), "project-2".to_string()]
        );
    }

    #[test]
    fn extra_merge_uses_person_over_project_over_global() {
        let mut global_extra = Mapping::new();
        global_extra.insert(yv("greeting"), yv("global"));
        global_extra.insert(yv("only_global"), yv("yes"));
        let global = GlobalConfig {
            extra: global_extra,
            ..GlobalConfig::default()
        };

        let mut project_extra = Mapping::new();
        project_extra.insert(yv("greeting"), yv("project"));
        project_extra.insert(yv("only_project"), yv("yes"));
        let project = ProjectConfig {
            extra: project_extra,
            ..ProjectConfig::default()
        };

        let mut person_extra = Mapping::new();
        person_extra.insert(yv("greeting"), yv("person"));
        person_extra.insert(yv("only_person"), yv("yes"));
        let person = PersonConfig {
            extra: person_extra,
            ..PersonConfig::default()
        };

        let cfg = effective_config(global, Some(project), Some(person));
        assert_eq!(cfg.global.extra.get(yv("greeting")), Some(&yv("person")));
        assert_eq!(cfg.global.extra.get(yv("only_global")), Some(&yv("yes")));
        assert_eq!(cfg.global.extra.get(yv("only_project")), Some(&yv("yes")));
        assert_eq!(cfg.global.extra.get(yv("only_person")), Some(&yv("yes")));
    }

    #[test]
    fn missing_overlays_pass_through_global_unchanged() {
        let mut extra = Mapping::new();
        extra.insert(yv("greeting"), yv("hello"));
        let global = GlobalConfig {
            people: vec![PersonEntry {
                name: "Owner".into(),
                email: "owner@example.com".into(),
                username: None,
                role: "admin".into(),
                proficiency: None,
                extra: Mapping::new(),
            }],
            checkout_root: Some("/Users/x".into()),
            extra,
            ..GlobalConfig::default()
        };

        let cfg = effective_config(global.clone(), None, None);

        assert_eq!(cfg.global.people, global.people);
        assert_eq!(cfg.global.checkout_root, global.checkout_root);
        assert_eq!(cfg.global.extra.get(yv("greeting")), Some(&yv("hello")));
        assert!(cfg.project.is_none());
        assert!(cfg.person.is_none());
    }

    #[test]
    fn find_person_entry_returns_match_by_email() {
        let cfg = Config {
            global: GlobalConfig {
                people: vec![
                    PersonEntry {
                        name: "Alice".into(),
                        email: "alice@example.com".into(),
                        username: None,
                        role: "member".into(),
                        proficiency: None,
                        extra: Mapping::new(),
                    },
                    PersonEntry {
                        name: "Owner".into(),
                        email: "owner@example.com".into(),
                        username: None,
                        role: "admin".into(),
                        proficiency: None,
                        extra: Mapping::new(),
                    },
                ],
                ..GlobalConfig::default()
            },
            project: None,
            person: None,
        };
        let found = find_person_entry(&cfg, "owner@example.com").expect("found owner");
        assert_eq!(found.name, "Owner");
        assert!(find_person_entry(&cfg, "missing@example.com").is_none());
    }

    #[test]
    fn empty_person_interests_does_not_clear_lower_precedence() {
        let global = GlobalConfig {
            interests: vec!["global-1".into()],
            ..GlobalConfig::default()
        };
        let person = PersonConfig::default(); // interests is empty

        let cfg = effective_config(global, None, Some(person));

        assert_eq!(cfg.global.interests, vec!["global-1".to_string()]);
    }

    #[test]
    fn empty_person_interests_does_not_block_project_overlay() {
        // RV-5: a present person overlay with empty interests must NOT shut
        // out a non-empty project overlay. Person > project > global as
        // first-non-empty.
        let global = GlobalConfig {
            interests: vec!["global-1".into()],
            ..GlobalConfig::default()
        };
        let mut project_extra = Mapping::new();
        project_extra.insert(
            yv("interests"),
            Value::Sequence(vec![yv("project-1"), yv("project-2")]),
        );
        let project = ProjectConfig {
            extra: project_extra,
            ..ProjectConfig::default()
        };
        let person = PersonConfig::default(); // interests is empty

        let cfg = effective_config(global, Some(project), Some(person));

        assert_eq!(
            cfg.global.interests,
            vec!["project-1".to_string(), "project-2".to_string()]
        );
    }
}
