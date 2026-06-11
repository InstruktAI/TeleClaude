//! v1-compatible validation for the loaded config overlays.
//!
//! Mirrors the public Pydantic constraints in
//! `teleclaude/config/schema.py` for the user-facing `teleclaude.yml`
//! surface: roster entries, scope-specific keys, project jobs,
//! integrator cutover flags, deployment channel pinning, and the legacy
//! `interests.tags` shape. Violations fail at load time rather than
//! riding through to runtime as opaque YAML.
//!
//! All violations surface as [`ConfigError::ValidationFailed`] (single
//! issue) or [`ConfigError::MergeConflict`] (duplicate roster email).

use std::collections::HashSet;

use serde_yaml::{Mapping, Value};

use crate::errors::ConfigError;
use crate::models::{
    ChannelSubscription, Config, DeploymentChannel, DeploymentConfig, GlobalConfig, PersonConfig,
    PersonEntry, ProjectConfig,
};

/// Roles accepted by v1's `PersonEntry.role` field.
pub const KNOWN_ROLES: &[&str] = &["admin", "member", "contributor", "newcomer"];

/// Slug character set v1's `validate_slug` accepts (lowercase alphanum +
/// dash + underscore, must start with alphanum, length 1..=64).
fn is_valid_slug(value: &str) -> bool {
    if value.is_empty() || value.len() > 64 {
        return false;
    }
    let mut chars = value.chars();
    match chars.next() {
        Some(c) if c.is_ascii_lowercase() || c.is_ascii_digit() => {}
        _ => return false,
    }
    chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_')
}

fn looks_like_email(value: &str) -> bool {
    if value.trim().is_empty() {
        return false;
    }
    // Cheap email shape check — present-at-sign with non-empty local and
    // domain parts. Production code does not authenticate on this; the
    // identity service is the auth boundary.
    let mut parts = value.splitn(2, '@');
    let local = parts.next().unwrap_or("");
    let domain = parts.next().unwrap_or("");
    !local.trim().is_empty() && !domain.trim().is_empty() && domain.contains('.')
}

fn validation_failed(path: &str, reason: impl Into<String>) -> ConfigError {
    ConfigError::ValidationFailed(format!("{path}: {}", reason.into()))
}

fn key(name: &str) -> Value {
    Value::String(name.to_string())
}

fn get<'a>(mapping: &'a Mapping, name: &str) -> Option<&'a Value> {
    mapping.get(key(name))
}

fn non_null(value: Option<&Value>) -> Option<&Value> {
    value.filter(|value| !matches!(value, Value::Null))
}

fn has_key(mapping: &Mapping, name: &str) -> bool {
    mapping.contains_key(key(name))
}

fn as_mapping<'a>(path: &str, value: &'a Value) -> Result<&'a Mapping, ConfigError> {
    match value {
        Value::Mapping(mapping) => Ok(mapping),
        _ => Err(validation_failed(path, "must be a mapping")),
    }
}

fn as_sequence<'a>(path: &str, value: &'a Value) -> Result<&'a Vec<Value>, ConfigError> {
    match value {
        Value::Sequence(sequence) => Ok(sequence),
        _ => Err(validation_failed(path, "must be a list")),
    }
}

fn as_str<'a>(path: &str, value: &'a Value) -> Result<&'a str, ConfigError> {
    match value {
        Value::String(value) => Ok(value),
        _ => Err(validation_failed(path, "must be a string")),
    }
}

fn as_bool(path: &str, value: &Value) -> Result<bool, ConfigError> {
    match value {
        Value::Bool(value) => Ok(*value),
        _ => Err(validation_failed(path, "must be a boolean")),
    }
}

fn as_i64(path: &str, value: &Value) -> Result<i64, ConfigError> {
    match value {
        Value::Number(value) => value
            .as_i64()
            .ok_or_else(|| validation_failed(path, "must be an integer")),
        _ => Err(validation_failed(path, "must be an integer")),
    }
}

fn validate_disallowed_keys(
    scope: &str,
    mapping: &Mapping,
    disallowed: &[&str],
) -> Result<(), ConfigError> {
    let present: Vec<&str> = disallowed
        .iter()
        .copied()
        .filter(|name| has_key(mapping, name))
        .collect();
    if present.is_empty() {
        return Ok(());
    }
    Err(validation_failed(
        scope,
        format!("keys not allowed at this level: {}", present.join(", ")),
    ))
}

fn validate_string_field(path: &str, mapping: &Mapping, name: &str) -> Result<(), ConfigError> {
    if let Some(value) = non_null(get(mapping, name)) {
        as_str(&format!("{path}.{name}"), value)?;
    }
    Ok(())
}

fn validate_int_range(
    path: &str,
    mapping: &Mapping,
    name: &str,
    min: i64,
    max: i64,
) -> Result<(), ConfigError> {
    if let Some(value) = non_null(get(mapping, name)) {
        let number = as_i64(&format!("{path}.{name}"), value)?;
        if !(min..=max).contains(&number) {
            return Err(validation_failed(
                &format!("{path}.{name}"),
                format!("must be between {min} and {max}"),
            ));
        }
    }
    Ok(())
}

fn validate_one_of(
    path: &str,
    mapping: &Mapping,
    name: &str,
    allowed: &[&str],
) -> Result<(), ConfigError> {
    if let Some(value) = non_null(get(mapping, name)) {
        let actual = as_str(&format!("{path}.{name}"), value)?;
        if !allowed.contains(&actual) {
            return Err(validation_failed(
                &format!("{path}.{name}"),
                format!("unknown value: {actual}"),
            ));
        }
    }
    Ok(())
}

fn is_valid_duration(value: &str) -> bool {
    let Some(unit) = value.chars().last() else {
        return false;
    };
    if !matches!(unit, 'm' | 'h' | 'd') {
        return false;
    }
    let number = &value[..value.len() - unit.len_utf8()];
    !number.is_empty()
        && number.chars().all(|c| c.is_ascii_digit())
        && number.parse::<u64>().is_ok_and(|value| value >= 1)
}

fn validate_time(path: &str, value: &str) -> Result<(), ConfigError> {
    let bytes = value.as_bytes();
    if bytes.len() != 5
        || !bytes[0].is_ascii_digit()
        || !bytes[1].is_ascii_digit()
        || bytes[2] != b':'
        || !bytes[3].is_ascii_digit()
        || !bytes[4].is_ascii_digit()
    {
        return Err(validation_failed(path, "expected HH:MM"));
    }
    let hour: u8 = value[0..2]
        .parse()
        .map_err(|_| validation_failed(path, "invalid hour"))?;
    let minute: u8 = value[3..5]
        .parse()
        .map_err(|_| validation_failed(path, "invalid minute"))?;
    if hour > 23 {
        return Err(validation_failed(path, "hour must be 00-23"));
    }
    if minute > 59 {
        return Err(validation_failed(path, "minute must be 00-59"));
    }
    Ok(())
}

fn validate_when(path: &str, value: &Value) -> Result<(), ConfigError> {
    let mapping = as_mapping(path, value)?;

    let every = non_null(get(mapping, "every"));
    let at = non_null(get(mapping, "at"));
    if every.is_some() == at.is_some() {
        return Err(validation_failed(
            path,
            "specify exactly one of 'every' or 'at'",
        ));
    }

    if let Some(value) = every {
        let every_value = as_str(&format!("{path}.every"), value)?;
        if !is_valid_duration(every_value) {
            return Err(validation_failed(
                &format!("{path}.every"),
                "expected <number><m|h|d> with a value of at least 1",
            ));
        }
    }

    if let Some(value) = at {
        match value {
            Value::String(time) => validate_time(&format!("{path}.at"), time)?,
            Value::Sequence(times) => {
                for (idx, time) in times.iter().enumerate() {
                    validate_time(
                        &format!("{path}.at[{idx}]"),
                        as_str(&format!("{path}.at[{idx}]"), time)?,
                    )?;
                }
            }
            _ => {
                return Err(validation_failed(
                    &format!("{path}.at"),
                    "must be a time or list",
                ))
            }
        }
    }

    if let Some(value) = non_null(get(mapping, "weekdays")) {
        let weekdays = as_sequence(&format!("{path}.weekdays"), value)?;
        for (idx, weekday) in weekdays.iter().enumerate() {
            let weekday = as_str(&format!("{path}.weekdays[{idx}]"), weekday)?;
            if !matches!(
                weekday,
                "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun"
            ) {
                return Err(validation_failed(
                    &format!("{path}.weekdays[{idx}]"),
                    format!("unknown weekday: {weekday}"),
                ));
            }
        }
        if !weekdays.is_empty() && at.is_none() {
            return Err(validation_failed(
                &format!("{path}.weekdays"),
                "requires 'at'",
            ));
        }
    }

    Ok(())
}

fn validate_job_schedule(path: &str, value: &Value) -> Result<(), ConfigError> {
    let mapping = as_mapping(path, value)?;
    validate_one_of(path, mapping, "category", &["subscription", "system"])?;
    validate_one_of(
        path,
        mapping,
        "schedule",
        &["hourly", "daily", "weekly", "monthly"],
    )?;
    validate_int_range(path, mapping, "preferred_hour", 0, 23)?;
    validate_int_range(path, mapping, "preferred_weekday", 0, 6)?;
    validate_int_range(path, mapping, "preferred_day", 1, 31)?;
    validate_string_field(path, mapping, "type")?;
    validate_string_field(path, mapping, "script")?;
    validate_string_field(path, mapping, "job")?;
    validate_string_field(path, mapping, "agent")?;
    validate_string_field(path, mapping, "thinking_mode")?;
    validate_string_field(path, mapping, "message")?;
    if let Some(value) = non_null(get(mapping, "timeout")) {
        as_i64(&format!("{path}.timeout"), value)?;
    }
    if let Some(value) = non_null(get(mapping, "when")) {
        validate_when(&format!("{path}.when"), value)?;
    }
    Ok(())
}

fn validate_jobs(path: &str, value: &Value) -> Result<(), ConfigError> {
    let mapping = as_mapping(path, value)?;
    for (name, job) in mapping {
        let job_name = as_str(path, name)?;
        validate_job_schedule(&format!("{path}.{job_name}"), job)?;
    }
    Ok(())
}

fn validate_business(path: &str, value: &Value) -> Result<(), ConfigError> {
    let mapping = as_mapping(path, value)?;
    if let Some(value) = non_null(get(mapping, "domains")) {
        let domains = as_mapping(&format!("{path}.domains"), value)?;
        for (domain, destination) in domains {
            as_str(&format!("{path}.domains.<key>"), domain)?;
            as_str(
                &format!("{path}.domains.{}", as_str(path, domain)?),
                destination,
            )?;
        }
    }
    Ok(())
}

fn validate_integrator(path: &str, value: &Value) -> Result<(), ConfigError> {
    let mapping = as_mapping(path, value)?;
    let Some(cutover) = non_null(get(mapping, "cutover")) else {
        return Ok(());
    };
    let cutover = as_mapping(&format!("{path}.cutover"), cutover)?;
    let enabled = non_null(get(cutover, "enabled"))
        .map(|value| as_bool(&format!("{path}.cutover.enabled"), value))
        .transpose()?
        .unwrap_or(false);
    let parity = non_null(get(cutover, "parity_evidence_accepted"))
        .map(|value| as_bool(&format!("{path}.cutover.parity_evidence_accepted"), value))
        .transpose()?
        .unwrap_or(false);
    if let Some(value) = non_null(get(cutover, "rollback_on_incomplete_parity")) {
        as_bool(
            &format!("{path}.cutover.rollback_on_incomplete_parity"),
            value,
        )?;
    }
    if enabled && !parity {
        return Err(validation_failed(
            &format!("{path}.cutover"),
            "enabled requires parity_evidence_accepted=true",
        ));
    }
    Ok(())
}

fn validate_deployment_mapping(path: &str, value: &Value) -> Result<(), ConfigError> {
    let mapping = as_mapping(path, value)?;
    validate_one_of(path, mapping, "channel", &["alpha", "beta", "stable"])?;
    let channel = non_null(get(mapping, "channel"))
        .map(|value| as_str(&format!("{path}.channel"), value))
        .transpose()?
        .unwrap_or("alpha");
    let pinned_minor = non_null(get(mapping, "pinned_minor"))
        .map(|value| as_str(&format!("{path}.pinned_minor"), value))
        .transpose()?
        .unwrap_or("");
    if channel == "stable" && pinned_minor.trim().is_empty() {
        return Err(validation_failed(
            &format!("{path}.pinned_minor"),
            "required when deployment.channel=stable",
        ));
    }
    Ok(())
}

fn validate_channel_subscriptions(path: &str, value: &Value) -> Result<(), ConfigError> {
    let subscriptions = as_sequence(path, value)?;
    for (idx, subscription) in subscriptions.iter().enumerate() {
        let item_path = format!("{path}[{idx}]");
        let mapping = as_mapping(&item_path, subscription)?;
        match non_null(get(mapping, "channel")) {
            Some(value) => {
                as_str(&format!("{item_path}.channel"), value)?;
            }
            None => {
                return Err(validation_failed(
                    &format!("{item_path}.channel"),
                    "is required",
                ));
            }
        }
        if let Some(value) = non_null(get(mapping, "target")) {
            as_mapping(&format!("{item_path}.target"), value)?;
        }
    }
    Ok(())
}

fn validate_global_project_surface(scope: &str, extra: &Mapping) -> Result<(), ConfigError> {
    if let Some(value) = non_null(get(extra, "business")) {
        validate_business(&format!("{scope}.business"), value)?;
    }
    if let Some(value) = non_null(get(extra, "hooks")) {
        as_mapping(&format!("{scope}.hooks"), value)?;
    }
    if let Some(value) = non_null(get(extra, "jobs")) {
        validate_jobs(&format!("{scope}.jobs"), value)?;
    }
    if let Some(value) = non_null(get(extra, "git")) {
        as_mapping(&format!("{scope}.git"), value)?;
    }
    if let Some(value) = non_null(get(extra, "integrator")) {
        validate_integrator(&format!("{scope}.integrator"), value)?;
    }
    if let Some(value) = non_null(get(extra, "deployment")) {
        validate_deployment_mapping(&format!("{scope}.deployment"), value)?;
    }
    if let Some(value) = non_null(get(extra, "channel_subscriptions")) {
        validate_channel_subscriptions(&format!("{scope}.channel_subscriptions"), value)?;
    }
    Ok(())
}

fn validate_project_extra_surface(scope: &str, extra: &Mapping) -> Result<(), ConfigError> {
    if let Some(value) = non_null(get(extra, "business")) {
        validate_business(&format!("{scope}.business"), value)?;
    }
    if let Some(value) = non_null(get(extra, "jobs")) {
        validate_jobs(&format!("{scope}.jobs"), value)?;
    }
    if let Some(value) = non_null(get(extra, "git")) {
        as_mapping(&format!("{scope}.git"), value)?;
    }
    if let Some(value) = non_null(get(extra, "integrator")) {
        validate_integrator(&format!("{scope}.integrator"), value)?;
    }
    Ok(())
}

fn validate_deployment(path: &str, deployment: &DeploymentConfig) -> Result<(), ConfigError> {
    let channel = deployment.channel_at_path(&format!("{path}.channel"))?;
    let pinned_minor = deployment.pinned_minor_at_path(&format!("{path}.pinned_minor"))?;
    if channel == DeploymentChannel::Stable && pinned_minor.trim().is_empty() {
        return Err(validation_failed(
            &format!("{path}.pinned_minor"),
            "required when deployment.channel=stable",
        ));
    }
    Ok(())
}

fn validate_project_channel_subscriptions(
    path: &str,
    subscriptions: &[ChannelSubscription],
) -> Result<(), ConfigError> {
    for (idx, subscription) in subscriptions.iter().enumerate() {
        let item_path = format!("{path}[{idx}]");
        subscription.channel_at_path(&format!("{item_path}.channel"))?;
        subscription.target_at_path(&format!("{item_path}.target"))?;
    }
    Ok(())
}

fn validate_creds(path: &str, value: &Value) -> Result<(), ConfigError> {
    let mapping = as_mapping(path, value)?;
    if let Some(value) = non_null(get(mapping, "telegram")) {
        let telegram = as_mapping(&format!("{path}.telegram"), value)?;
        validate_string_field(&format!("{path}.telegram"), telegram, "user_name")?;
        if let Some(value) = non_null(get(telegram, "user_id")) {
            as_i64(&format!("{path}.telegram.user_id"), value)?;
        }
        validate_string_field(&format!("{path}.telegram"), telegram, "chat_id")?;
    }
    if let Some(value) = non_null(get(mapping, "discord")) {
        let discord = as_mapping(&format!("{path}.discord"), value)?;
        validate_string_field(&format!("{path}.discord"), discord, "user_id")?;
    }
    if let Some(value) = non_null(get(mapping, "whatsapp")) {
        let whatsapp = as_mapping(&format!("{path}.whatsapp"), value)?;
        validate_string_field(&format!("{path}.whatsapp"), whatsapp, "phone_number")?;
    }
    Ok(())
}

/// Validate a single [`PersonEntry`].
pub fn validate_person_entry(person: &PersonEntry) -> Result<(), ConfigError> {
    if person.name.trim().is_empty() {
        return Err(ConfigError::ValidationFailed(
            "person entry has empty name".into(),
        ));
    }
    if !looks_like_email(&person.email) {
        return Err(ConfigError::ValidationFailed(format!(
            "person {} has malformed email: {}",
            person.name, person.email
        )));
    }
    if !KNOWN_ROLES.contains(&person.role.as_str()) {
        return Err(ConfigError::ValidationFailed(format!(
            "person {} carries unknown role: {}",
            person.name, person.role
        )));
    }
    Ok(())
}

/// Validate the global overlay's roster and global/project config surface.
pub fn validate_global(global: &GlobalConfig) -> Result<(), ConfigError> {
    validate_disallowed_keys(
        "global",
        &global.extra,
        &["creds", "notifications", "timezone"],
    )?;
    validate_global_project_surface("global", &global.extra)?;

    let mut seen_emails: HashSet<String> = HashSet::new();
    for person in &global.people {
        validate_person_entry(person)?;
        let normalized = person.email.trim().to_lowercase();
        if !seen_emails.insert(normalized.clone()) {
            return Err(ConfigError::MergeConflict {
                field: "people.email".into(),
                reason: format!("duplicate email in roster: {normalized}"),
            });
        }
    }
    Ok(())
}

/// Validate the project overlay.
pub fn validate_project(project: &ProjectConfig) -> Result<(), ConfigError> {
    if let Some(slug) = project.project_slug.as_deref() {
        let slug = slug.trim();
        if !slug.is_empty() && !is_valid_slug(slug) {
            return Err(ConfigError::ValidationFailed(format!(
                "project_slug is not a valid slug: {slug}"
            )));
        }
    }
    validate_disallowed_keys(
        "project",
        &project.extra,
        &["people", "ops", "creds", "notifications", "timezone"],
    )?;
    validate_project_extra_surface("project", &project.extra)?;
    validate_deployment("project.deployment", &project.deployment)?;
    validate_project_channel_subscriptions(
        "project.channel_subscriptions",
        &project.channel_subscriptions,
    )?;
    Ok(())
}

/// Validate the per-person overlay.
pub fn validate_person_overlay(person: &PersonConfig) -> Result<(), ConfigError> {
    validate_disallowed_keys(
        "per-person",
        &person.extra,
        &["people", "ops", "business", "timezone"],
    )?;
    if let Some(value) = non_null(get(&person.extra, "creds")) {
        validate_creds("per-person.creds", value)?;
    }
    Ok(())
}

/// Validate the composed effective [`Config`].
pub fn validate(config: &Config) -> Result<(), ConfigError> {
    validate_global(&config.global)?;
    if let Some(project) = config.project.as_ref() {
        validate_project(project)?;
    }
    if let Some(person) = config.person.as_ref() {
        validate_person_overlay(person)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{GlobalConfig, PersonConfig, PersonEntry, ProjectConfig};

    fn person(name: &str, email: &str, role: &str) -> PersonEntry {
        PersonEntry {
            name: name.into(),
            email: email.into(),
            username: None,
            role: role.into(),
            proficiency: None,
            extra: Mapping::new(),
        }
    }

    #[test]
    fn validate_global_accepts_known_roles_and_unique_emails() {
        let global = GlobalConfig {
            people: vec![
                person("Owner", "owner@example.com", "admin"),
                person("Member", "member@example.com", "contributor"),
            ],
            ..GlobalConfig::default()
        };
        validate_global(&global).expect("valid roster");
    }

    #[test]
    fn validate_global_rejects_unknown_role() {
        let global = GlobalConfig {
            people: vec![person("Customer", "customer@example.com", "customer")],
            ..GlobalConfig::default()
        };
        let err = validate_global(&global).expect_err("unknown role rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_global_rejects_malformed_email() {
        let global = GlobalConfig {
            people: vec![person("Owner", "not-an-email", "admin")],
            ..GlobalConfig::default()
        };
        let err = validate_global(&global).expect_err("malformed email rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_global_rejects_empty_name() {
        let global = GlobalConfig {
            people: vec![person("", "owner@example.com", "admin")],
            ..GlobalConfig::default()
        };
        let err = validate_global(&global).expect_err("empty name rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_global_rejects_duplicate_email_with_merge_conflict() {
        let global = GlobalConfig {
            people: vec![
                person("Owner", "owner@example.com", "admin"),
                person("Owner Two", "Owner@Example.com", "member"),
            ],
            ..GlobalConfig::default()
        };
        let err = validate_global(&global).expect_err("duplicate email rejected");
        match err {
            ConfigError::MergeConflict { field, .. } => {
                assert_eq!(field, "people.email");
            }
            other => panic!("expected MergeConflict, got {other:?}"),
        }
    }

    #[test]
    fn validate_global_rejects_person_only_keys() {
        let global: GlobalConfig = serde_yaml::from_str("creds: {}\n").expect("global yaml");
        let err = validate_global(&global).expect_err("person-only key rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_accepts_valid_slug() {
        let project = ProjectConfig {
            project_slug: Some("teleclaude_v2-spine".into()),
            ..ProjectConfig::default()
        };
        validate_project(&project).expect("valid slug");
    }

    #[test]
    fn validate_project_rejects_invalid_slug() {
        let project = ProjectConfig {
            project_slug: Some("Invalid Slug!".into()),
            ..ProjectConfig::default()
        };
        let err = validate_project(&project).expect_err("invalid slug");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_global_only_keys() {
        let project: ProjectConfig = serde_yaml::from_str("people: []\n").expect("project yaml");
        let err = validate_project(&project).expect_err("global-only key rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_invalid_job_when() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
jobs:
  sweep:
    category: system
    when:
      every: 0m
"#,
        )
        .expect("project yaml");
        let err = validate_project(&project).expect_err("invalid job schedule rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_weekdays_without_wall_clock_time() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
jobs:
  sweep:
    when:
      every: 10m
      weekdays: [mon]
"#,
        )
        .expect("project yaml");
        let err = validate_project(&project).expect_err("invalid weekday mode rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_accepts_valid_jobs_cutover_and_deployment() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
jobs:
  sweep:
    category: system
    when:
      at: ['09:00', '14:30']
    preferred_hour: 6
    preferred_weekday: 0
    preferred_day: 1
integrator:
  cutover:
    enabled: true
    parity_evidence_accepted: true
deployment:
  channel: stable
  pinned_minor: '2.4'
"#,
        )
        .expect("project yaml");
        validate_project(&project).expect("valid project surface");
    }

    #[test]
    fn validate_project_rejects_cutover_enabled_without_parity() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
integrator:
  cutover:
    enabled: true
"#,
        )
        .expect("project yaml");
        let err = validate_project(&project).expect_err("cutover rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_stable_deployment_without_pin() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
deployment:
  channel: stable
"#,
        )
        .expect("project yaml");
        let err = validate_project(&project).expect_err("deployment rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_unknown_deployment_channel() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
deployment:
  channel: canary
"#,
        )
        .expect("project yaml");

        let err = validate_project(&project).expect_err("deployment rejected");

        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_non_string_deployment_channel_after_load() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
deployment:
  channel: 42
"#,
        )
        .expect("project yaml");

        let err = validate_project(&project).expect_err("deployment rejected");

        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_non_string_deployment_pin_after_load() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
deployment:
  channel: stable
  pinned_minor: 42
"#,
        )
        .expect("project yaml");

        let err = validate_project(&project).expect_err("deployment rejected");

        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_requires_channel_subscription_channel() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
channel_subscriptions:
- target: {}
"#,
        )
        .expect("project yaml");

        let err = validate_project(&project).expect_err("subscription rejected");

        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_null_channel_subscription_channel() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
channel_subscriptions:
- channel: null
"#,
        )
        .expect("project yaml");

        let err = validate_project(&project).expect_err("subscription rejected");

        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_rejects_non_string_channel_subscription_channel() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
channel_subscriptions:
- channel: 42
"#,
        )
        .expect("project yaml");

        let err = validate_project(&project).expect_err("subscription rejected");

        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_project_accepts_empty_string_channel_subscription_channel() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
channel_subscriptions:
- channel: ""
"#,
        )
        .expect("project yaml");

        validate_project(&project).expect("subscription accepted");
    }

    #[test]
    fn validate_project_rejects_non_mapping_channel_subscription_target() {
        let project: ProjectConfig = serde_yaml::from_str(
            r#"
channel_subscriptions:
- channel: inbound.whatsapp
  target: invalid
"#,
        )
        .expect("project yaml");

        let err = validate_project(&project).expect_err("subscription rejected");

        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_person_overlay_rejects_project_only_keys() {
        let person: PersonConfig = serde_yaml::from_str("business: {}\n").expect("person yaml");
        let err = validate_person_overlay(&person).expect_err("project-only key rejected");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }

    #[test]
    fn validate_person_overlay_accepts_creds_shape() {
        let person: PersonConfig = serde_yaml::from_str(
            r#"
creds:
  telegram:
    user_name: Morriz
    user_id: 123
  discord:
    user_id: '123456'
"#,
        )
        .expect("person yaml");
        validate_person_overlay(&person).expect("valid person overlay");
    }

    #[test]
    fn validate_composed_config_runs_all_passes() {
        let config = Config {
            global: GlobalConfig {
                people: vec![person("Owner", "owner@example.com", "admin")],
                ..GlobalConfig::default()
            },
            project: Some(ProjectConfig {
                project_slug: Some("ok".into()),
                ..ProjectConfig::default()
            }),
            person: Some(PersonConfig::default()),
        };
        validate(&config).expect("composed config validates");
    }

    #[test]
    fn validate_composed_config_surfaces_global_failure() {
        let config = Config {
            global: GlobalConfig {
                people: vec![person("Owner", "owner@example.com", "wizard")],
                ..GlobalConfig::default()
            },
            project: None,
            person: None,
        };
        let err = validate(&config).expect_err("global failure surfaces");
        assert!(matches!(err, ConfigError::ValidationFailed(_)));
    }
}
