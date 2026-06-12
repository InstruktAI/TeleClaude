use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::errors::ReconciliationError;
use crate::policy::TargetVersion;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConvergenceRunStatus {
    Converged,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConvergenceRunRecord {
    pub run_id: String,
    pub from_version: String,
    pub to_version: TargetVersion,
    pub status: ConvergenceRunStatus,
    pub failed_step: Option<String>,
    pub failure_context: Option<String>,
    pub recorded_at: DateTime<Utc>,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct LedgerDocument {
    #[serde(default)]
    applied_versions: BTreeSet<TargetVersion>,
    #[serde(default)]
    runs: BTreeMap<String, ConvergenceRunRecord>,
}

#[derive(Debug)]
pub struct AppliedVersionLedger {
    path: PathBuf,
    lock: Mutex<()>,
}

impl AppliedVersionLedger {
    pub fn at_path(path: impl Into<PathBuf>) -> Self {
        Self {
            path: path.into(),
            lock: Mutex::new(()),
        }
    }

    pub fn under_home(home: &Path) -> Self {
        Self::at_path(home.join("reconciliation").join("applied_versions.json"))
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn is_applied(&self, target: &TargetVersion) -> Result<bool, ReconciliationError> {
        let _guard = self
            .lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        Ok(self.load()?.applied_versions.contains(target))
    }

    pub fn mark_applied(&self, target: &TargetVersion) -> Result<(), ReconciliationError> {
        let _guard = self
            .lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut document = self.load()?;
        document.applied_versions.insert(target.clone());
        self.store(&document)
    }

    pub fn record_run(&self, record: ConvergenceRunRecord) -> Result<(), ReconciliationError> {
        let _guard = self
            .lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut document = self.load()?;
        document.runs.insert(record.run_id.clone(), record);
        self.store(&document)
    }

    pub fn runs(&self) -> Result<Vec<ConvergenceRunRecord>, ReconciliationError> {
        let _guard = self
            .lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        Ok(self.load()?.runs.into_values().collect())
    }

    fn load(&self) -> Result<LedgerDocument, ReconciliationError> {
        match fs::read_to_string(&self.path) {
            Ok(raw) => Ok(serde_json::from_str(&raw)?),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                Ok(LedgerDocument::default())
            }
            Err(error) => Err(error.into()),
        }
    }

    fn store(&self, document: &LedgerDocument) -> Result<(), ReconciliationError> {
        let parent = self
            .path
            .parent()
            .ok_or_else(|| ReconciliationError::MissingLedgerParent(self.path.clone()))?;
        fs::create_dir_all(parent)?;
        let raw = serde_json::to_string_pretty(document)?;
        let tmp = self.path.with_extension("json.tmp");
        fs::write(&tmp, raw)?;
        fs::rename(tmp, &self.path)?;
        Ok(())
    }
}
