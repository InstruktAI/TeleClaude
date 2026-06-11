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

use crate::errors::ConfigError;

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
    #[serde(default)]
    pub deployment: DeploymentConfig,
    #[serde(default)]
    pub hooks: HooksConfig,
    #[serde(default)]
    pub channel_subscriptions: Vec<ChannelSubscription>,
    #[serde(flatten)]
    pub extra: Mapping,
}

/// Release channel declared by a project deployment block.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeploymentChannel {
    Alpha,
    Beta,
    Stable,
}

impl DeploymentChannel {
    fn from_str(path: &str, value: &str) -> Result<Self, ConfigError> {
        match value {
            "alpha" => Ok(Self::Alpha),
            "beta" => Ok(Self::Beta),
            "stable" => Ok(Self::Stable),
            actual => Err(ConfigError::ValidationFailed(format!(
                "{path}: unknown value: {actual}"
            ))),
        }
    }
}

/// Project deployment release-channel configuration.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DeploymentConfig {
    #[serde(default = "default_deployment_channel_raw", rename = "channel")]
    channel_raw: Value,
    #[serde(
        default = "default_deployment_pinned_minor_raw",
        rename = "pinned_minor"
    )]
    pinned_minor_raw: Value,
}

impl Default for DeploymentConfig {
    fn default() -> Self {
        Self {
            channel_raw: default_deployment_channel_raw(),
            pinned_minor_raw: default_deployment_pinned_minor_raw(),
        }
    }
}

impl DeploymentConfig {
    pub fn channel(&self) -> Result<DeploymentChannel, ConfigError> {
        self.channel_at_path("project.deployment.channel")
    }

    pub(crate) fn channel_at_path(&self, path: &str) -> Result<DeploymentChannel, ConfigError> {
        match &self.channel_raw {
            Value::Null => Ok(DeploymentChannel::Alpha),
            Value::String(value) => DeploymentChannel::from_str(path, value),
            _ => Err(ConfigError::ValidationFailed(format!(
                "{path}: must be a string"
            ))),
        }
    }

    pub fn pinned_minor(&self) -> Result<&str, ConfigError> {
        self.pinned_minor_at_path("project.deployment.pinned_minor")
    }

    pub(crate) fn pinned_minor_at_path(&self, path: &str) -> Result<&str, ConfigError> {
        match &self.pinned_minor_raw {
            Value::Null => Ok(""),
            Value::String(value) => Ok(value),
            _ => Err(ConfigError::ValidationFailed(format!(
                "{path}: must be a string"
            ))),
        }
    }
}

fn default_deployment_channel_raw() -> Value {
    Value::String("alpha".into())
}

fn default_deployment_pinned_minor_raw() -> Value {
    Value::String(String::new())
}

/// Inbound hook source configuration.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct InboundHook {
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default)]
    pub verify_token: Option<String>,
    #[serde(default)]
    pub secret: Option<String>,
    #[serde(default)]
    pub normalizer: Option<String>,
    #[serde(flatten)]
    pub extra: Mapping,
}

/// Project hook configuration.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct HooksConfig {
    #[serde(default)]
    pub inbound: std::collections::BTreeMap<String, InboundHook>,
    #[serde(flatten)]
    pub extra: Mapping,
}

/// Project channel subscription routing entry.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChannelSubscription {
    #[serde(default, rename = "channel")]
    channel_raw: Option<Value>,
    #[serde(default)]
    pub filter: Option<Value>,
    #[serde(default, rename = "target")]
    target_raw: Option<Value>,
    #[serde(flatten)]
    pub extra: Mapping,
}

impl ChannelSubscription {
    pub fn channel(&self) -> Result<&str, ConfigError> {
        self.channel_at_path("project.channel_subscriptions[].channel")
    }

    pub(crate) fn channel_at_path(&self, path: &str) -> Result<&str, ConfigError> {
        match self.channel_raw.as_ref() {
            Some(Value::String(value)) => Ok(value),
            Some(Value::Null) | None => Err(ConfigError::ValidationFailed(format!(
                "{path}: is required"
            ))),
            Some(_) => Err(ConfigError::ValidationFailed(format!(
                "{path}: must be a string"
            ))),
        }
    }

    pub fn target(&self) -> Result<Option<&Mapping>, ConfigError> {
        self.target_at_path("project.channel_subscriptions[].target")
    }

    pub(crate) fn target_at_path(&self, path: &str) -> Result<Option<&Mapping>, ConfigError> {
        match self.target_raw.as_ref() {
            Some(Value::Mapping(mapping)) => Ok(Some(mapping)),
            Some(Value::Null) | None => Ok(None),
            Some(_) => Err(ConfigError::ValidationFailed(format!(
                "{path}: must be a mapping"
            ))),
        }
    }
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
  expertise:
    python: expert
- name: tester
  email: tester@instrukt.ai
  role: contributor
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
    fn project_config_deserializes_typed_fleet_surface_and_preserves_extra() {
        let yaml = r#"
deployment:
  channel: beta
  pinned_minor: ''
hooks:
  inbound:
    whatsapp:
      path: /hooks/whatsapp
      verify_token: verify-token
      secret: webhook-secret
      normalizer: whatsapp
    github:
      path: /hooks/github
channel_subscriptions:
- channel: inbound.whatsapp
  target:
    kind: workflow
unrelated:
  still: extra
"#;
        let project: ProjectConfig = serde_yaml::from_str(yaml).expect("deserialize project");

        assert_eq!(
            project.deployment.channel().expect("channel"),
            DeploymentChannel::Beta
        );
        assert_eq!(project.deployment.pinned_minor().expect("pin"), "");
        let whatsapp = project
            .hooks
            .inbound
            .get("whatsapp")
            .expect("whatsapp hook");
        assert_eq!(whatsapp.path.as_deref(), Some("/hooks/whatsapp"));
        assert_eq!(whatsapp.verify_token.as_deref(), Some("verify-token"));
        assert_eq!(whatsapp.secret.as_deref(), Some("webhook-secret"));
        assert_eq!(whatsapp.normalizer.as_deref(), Some("whatsapp"));
        assert_eq!(
            project.channel_subscriptions[0]
                .channel()
                .expect("subscription channel"),
            "inbound.whatsapp"
        );
        assert!(project
            .extra
            .contains_key(serde_yaml::Value::String("unrelated".into())));
        assert!(!project
            .extra
            .contains_key(serde_yaml::Value::String("deployment".into())));
    }

    #[test]
    fn absent_deployment_uses_alpha_channel_and_empty_pin() {
        let project: ProjectConfig =
            serde_yaml::from_str("project_name: TeleClaude\n").expect("deserialize project");

        assert_eq!(
            project.deployment.channel().expect("channel"),
            DeploymentChannel::Alpha
        );
        assert_eq!(project.deployment.pinned_minor().expect("pin"), "");
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
