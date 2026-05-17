//! Config domain model.
//!
//! The Rust model is intentionally narrow: only the fields the v2 spine
//! reasons about are explicit. Everything else lands in an `extra`
//! `serde_yaml::Mapping` so the model deserializes any real v1
//! `teleclaude.yml` without rejection — overlay resolution and validation
//! happen on the explicit fields, while unknown content rides along
//! unchanged for inspection by downstream services.

use serde::{Deserialize, Deserializer, Serialize};
use serde_yaml::{Mapping, Value};

/// One person entry from the global `people` list.
///
/// Mirrors `teleclaude.config.schema.PersonEntry`. Role here is a free-form
/// string because v1 carries values like `"admin"`, `"customer"`, and other
/// installation-specific names; the migration tool maps these onto the
/// identity service's `Role` enum at insert time.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PersonEntry {
    pub name: String,
    pub email: String,
    #[serde(default)]
    pub username: Option<String>,
    pub role: String,
    #[serde(default)]
    pub proficiency: Option<String>,
    #[serde(flatten)]
    pub extra: Mapping,
}

/// Global-level configuration.
///
/// Mirrors `teleclaude.config.schema.GlobalConfig` but keeps only the
/// fields the v2 spine references directly. Other top-level keys ride
/// along in [`Self::extra`].
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct GlobalConfig {
    #[serde(default)]
    pub people: Vec<PersonEntry>,
    #[serde(default, deserialize_with = "deserialize_interests")]
    pub interests: Vec<String>,
    #[serde(default)]
    pub checkout_root: Option<String>,
    #[serde(flatten)]
    pub extra: Mapping,
}

/// Project-level configuration.
///
/// Mirrors `teleclaude.config.schema.ProjectConfig`. The v2 spine
/// references the slug and the language directly; everything else flows
/// through [`Self::extra`].
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectConfig {
    #[serde(default, deserialize_with = "deserialize_optional_trimmed_string")]
    pub project_slug: Option<String>,
    #[serde(default)]
    pub project_name: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub language: Option<String>,
    #[serde(default)]
    pub languages: Vec<String>,
    #[serde(default)]
    pub frontend_root: Option<String>,
    #[serde(flatten)]
    pub extra: Mapping,
}

/// Per-person configuration.
///
/// Mirrors `teleclaude.config.schema.PersonConfig`. Only the spine-relevant
/// fields are explicit; everything else flows through [`Self::extra`].
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct PersonConfig {
    #[serde(default, deserialize_with = "deserialize_interests")]
    pub interests: Vec<String>,
    #[serde(default)]
    pub invite_token: Option<String>,
    #[serde(flatten)]
    pub extra: Mapping,
}

/// Effective composed configuration.
///
/// Produced by overlay resolution from the three source files. Global is
/// always present; project and person overlays are optional per the
/// auth-model and services design.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Config {
    pub global: GlobalConfig,
    #[serde(default)]
    pub project: Option<ProjectConfig>,
    #[serde(default)]
    pub person: Option<PersonConfig>,
}

fn deserialize_optional_trimmed_string<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<String>::deserialize(deserializer)?;
    Ok(value.and_then(|raw| {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    }))
}

fn deserialize_interests<'de, D>(deserializer: D) -> Result<Vec<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    match value {
        Value::Null => Ok(Vec::new()),
        Value::Sequence(items) => sequence_to_strings(items).map_err(serde::de::Error::custom),
        Value::Mapping(mapping) => {
            let tags_key = Value::String("tags".into());
            match mapping.get(&tags_key) {
                Some(Value::Sequence(items)) => {
                    sequence_to_strings(items.clone()).map_err(serde::de::Error::custom)
                }
                Some(_) => Err(serde::de::Error::custom(
                    "interests.tags must be a list of strings",
                )),
                None => Err(serde::de::Error::custom(
                    "legacy interests mapping must contain tags",
                )),
            }
        }
        _ => Err(serde::de::Error::custom(
            "interests must be a list or {tags: [...]} mapping",
        )),
    }
}

fn sequence_to_strings(items: Vec<Value>) -> Result<Vec<String>, String> {
    items
        .into_iter()
        .map(|item| match item {
            Value::String(value) => Ok(value),
            other => Err(format!("interest must be a string, got {other:?}")),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn global_config_accepts_real_world_yaml_shape() {
        // Subset of the actual ~/.teleclaude/teleclaude.yml structure.
        let yaml = r#"
people:
- name: Maurice Faber
  email: maurice@instrukt.ai
  username: Morriz
  role: admin
  proficiency: expert
  expertise:
    python: expert
- name: tester
  email: tester@instrukt.ai
  role: contributor
  proficiency: expert
interests:
- ai-agents
- rust
checkout_root: /Users/x/Workspace
event_domains:
  domains:
    software-development:
      name: software-development
"#;

        let config: GlobalConfig = serde_yaml::from_str(yaml).expect("deserialize global config");

        assert_eq!(config.people.len(), 2);
        assert_eq!(config.people[0].name, "Maurice Faber");
        assert_eq!(config.people[0].email, "maurice@instrukt.ai");
        assert_eq!(config.people[0].role, "admin");
        assert_eq!(config.people[1].name, "tester");
        assert_eq!(config.checkout_root.as_deref(), Some("/Users/x/Workspace"));
        // Unknown top-level keys (event_domains) ride in extra.
        assert!(
            config
                .extra
                .contains_key(serde_yaml::Value::String("event_domains".into())),
            "event_domains must land in the extra catch-all"
        );
    }

    #[test]
    fn project_config_round_trip() {
        let yaml = r#"
project_slug: "  teleclaude  "
project_name: TeleClaude
language: python
languages:
- python
- rust
frontend_root: frontend
git:
  remote: origin
"#;
        let project: ProjectConfig = serde_yaml::from_str(yaml).expect("deserialize project");
        assert_eq!(project.project_slug.as_deref(), Some("teleclaude"));
        assert_eq!(project.project_name.as_deref(), Some("TeleClaude"));
        assert_eq!(project.languages, vec!["python", "rust"]);
        assert_eq!(project.frontend_root.as_deref(), Some("frontend"));
        assert!(project
            .extra
            .contains_key(serde_yaml::Value::String("git".into())));
    }

    #[test]
    fn person_entry_carries_extra_fields() {
        let yaml = r#"
name: Owner
email: owner@example.com
role: admin
proficiency: expert
expertise:
  rust: advanced
telegram_user: ownerbot
"#;
        let entry: PersonEntry = serde_yaml::from_str(yaml).expect("deserialize person entry");
        assert_eq!(entry.name, "Owner");
        assert_eq!(entry.role, "admin");
        assert_eq!(entry.proficiency.as_deref(), Some("expert"));
        assert_eq!(entry.extra.len(), 2);
    }

    #[test]
    fn empty_yaml_yields_defaults() {
        let yaml = "{}";
        let global: GlobalConfig = serde_yaml::from_str(yaml).expect("deserialize empty");
        assert!(global.people.is_empty());
        assert!(global.checkout_root.is_none());
        assert!(global.extra.is_empty());
    }

    #[test]
    fn legacy_interests_tags_mapping_deserializes_to_list() {
        let global: GlobalConfig = serde_yaml::from_str("interests:\n  tags:\n  - ai\n  - ops\n")
            .expect("global interests");
        assert_eq!(global.interests, vec!["ai", "ops"]);

        let person: PersonConfig =
            serde_yaml::from_str("interests:\n  tags:\n  - devtools\n").expect("person interests");
        assert_eq!(person.interests, vec!["devtools"]);
    }

    #[test]
    fn blank_project_slug_deserializes_to_none() {
        let project: ProjectConfig =
            serde_yaml::from_str("project_slug: '   '\n").expect("deserialize project");
        assert!(project.project_slug.is_none());
    }
}
