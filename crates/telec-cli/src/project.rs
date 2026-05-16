//! Project-context resolution for the CLI.
//!
//! v2 makes projects first-class. Every workflow operation requires a
//! [`ProjectId`]; this module turns the `--project` flag (or the cwd's
//! basename) into that id via [`WorkflowService::find_or_create_project`].

use std::path::Path;

use anyhow::{anyhow, Context, Result};
use shared::ProjectId;
use workflow::WorkflowService;

/// Resolve the project to operate against.
///
/// Precedence:
/// 1. `override_name` (the `--project` global flag) — used as the project
///    name; `root_path` is the current working directory.
/// 2. Otherwise the cwd's final path component is treated as the project
///    name and the cwd itself is the `root_path`.
///
/// Either way the project is upserted via
/// [`WorkflowService::find_or_create_project`] so a first-run invocation
/// creates the row.
pub async fn resolve_project(
    service: &WorkflowService,
    override_name: Option<&str>,
) -> Result<ProjectId> {
    let cwd = std::env::current_dir().context("read current working directory")?;
    let name = match override_name {
        Some(name) if !name.is_empty() => name.to_string(),
        _ => derive_name_from_cwd(&cwd)?,
    };
    let root_path = cwd
        .to_str()
        .ok_or_else(|| anyhow!("current working directory is not valid UTF-8"))?;

    Ok(service.find_or_create_project(&name, root_path).await?)
}

fn derive_name_from_cwd(cwd: &Path) -> Result<String> {
    cwd.file_name()
        .and_then(|os| os.to_str())
        .map(|s| s.to_string())
        .ok_or_else(|| anyhow!("cannot derive project name from cwd: {}", cwd.display()))
}
