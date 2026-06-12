use std::fmt;

use config::{DeploymentChannel, DeploymentConfig};
use serde::{Deserialize, Serialize};

use crate::errors::ReconciliationError;

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct TargetVersion(String);

impl TargetVersion {
    pub fn new(value: impl Into<String>) -> Result<Self, ReconciliationError> {
        let raw = value.into();
        let trimmed = raw.trim().trim_start_matches('v');
        if trimmed.is_empty() {
            return Err(ReconciliationError::InvalidTargetVersion(raw));
        }
        Ok(Self(trimmed.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    fn minor_series(&self) -> Option<String> {
        let mut parts = self.0.split('.');
        let major = parts.next()?.trim();
        let minor = parts.next()?.trim();
        if major.is_empty() || minor.is_empty() {
            return None;
        }
        Some(format!("{major}.{minor}"))
    }
}

impl fmt::Display for TargetVersion {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReleaseKind {
    Mainline,
    PublishedRelease,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReleaseSignal {
    pub target: TargetVersion,
    pub kind: ReleaseKind,
    pub idempotency_key: String,
}

impl ReleaseSignal {
    pub fn mainline(
        version: impl Into<String>,
        idempotency_key: impl Into<String>,
    ) -> Result<Self, ReconciliationError> {
        Ok(Self {
            target: TargetVersion::new(version)?,
            kind: ReleaseKind::Mainline,
            idempotency_key: idempotency_key.into(),
        })
    }

    pub fn published_release(
        version: impl Into<String>,
        idempotency_key: impl Into<String>,
    ) -> Result<Self, ReconciliationError> {
        Ok(Self {
            target: TargetVersion::new(version)?,
            kind: ReleaseKind::PublishedRelease,
            idempotency_key: idempotency_key.into(),
        })
    }
}

pub fn select_target(
    signal: &ReleaseSignal,
    deployment: &DeploymentConfig,
) -> Result<Option<TargetVersion>, ReconciliationError> {
    match deployment.channel()? {
        DeploymentChannel::Alpha => Ok(Some(signal.target.clone())),
        DeploymentChannel::Beta => {
            if signal.kind == ReleaseKind::PublishedRelease {
                Ok(Some(signal.target.clone()))
            } else {
                Ok(None)
            }
        }
        DeploymentChannel::Stable => stable_target(signal, deployment),
    }
}

fn stable_target(
    signal: &ReleaseSignal,
    deployment: &DeploymentConfig,
) -> Result<Option<TargetVersion>, ReconciliationError> {
    if signal.kind != ReleaseKind::PublishedRelease {
        return Ok(None);
    }
    let pinned_minor = deployment.pinned_minor()?.trim();
    if pinned_minor.is_empty() {
        return Ok(None);
    }
    if signal.target.minor_series().as_deref() == Some(pinned_minor) {
        Ok(Some(signal.target.clone()))
    } else {
        Ok(None)
    }
}

#[cfg(test)]
mod tests {
    use config::ProjectConfig;

    use super::*;

    fn deployment(yaml: &str) -> DeploymentConfig {
        serde_yaml::from_str::<ProjectConfig>(yaml)
            .expect("project config parses")
            .deployment
    }

    #[test]
    fn stable_matches_target_minor_series_without_leading_v() {
        let signal = ReleaseSignal::published_release("v1.2.5", "delivery-1").expect("signal");
        let deployment = deployment(
            r#"
deployment:
  channel: stable
  pinned_minor: '1.2'
"#,
        );

        let target = select_target(&signal, &deployment)
            .expect("policy evaluates")
            .expect("target selected");

        assert_eq!(target.as_str(), "1.2.5");
    }
}
