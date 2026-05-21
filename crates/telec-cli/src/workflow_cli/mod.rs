//! `telec workflow` subtree.
//!
//! This namespace hosts v2-native workflow operations that do not belong to
//! the legacy-compatible `telec todo` transition surface.

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use clap::{ArgAction, Args, Subcommand};
use identity::Principal;
use shared::{ProjectId, Slug};
use workflow::models::{CreationMode, TodoDiff};
use workflow::service::{CreateTodoArgs, UpdateTodoArgs};
use workflow::WorkflowService;

use crate::output;
use crate::todo::{parse_after_values, parse_artifact_name, parse_kind};

#[derive(Args, Debug)]
pub struct WorkflowArgs {
    #[command(subcommand)]
    pub command: WorkflowCommand,
}

#[derive(Subcommand, Debug)]
pub enum WorkflowCommand {
    /// Manage workflow todos.
    Todo(WorkflowTodoArgs),
    /// Manage workflow artifacts.
    Artifacts(WorkflowArtifactsArgs),
}

#[derive(Args, Debug)]
pub struct WorkflowTodoArgs {
    #[command(subcommand)]
    pub command: WorkflowTodoCommand,
}

#[derive(Subcommand, Debug)]
pub enum WorkflowTodoCommand {
    /// Create a todo with substantive input content.
    Create(WorkflowCreateArgs),
    /// Atomically update a live todo's metadata, dependencies, kind, and/or content.
    Update(WorkflowUpdateArgs),
    /// Atomically rename a live todo across workflow-owned surfaces.
    Rename(WorkflowRenameArgs),
    /// Show the refinement diff for one todo.
    Diff(WorkflowTodoDiffArgs),
}

#[derive(Args, Debug)]
pub struct WorkflowCreateArgs {
    /// Todo slug (unique per project).
    pub slug: String,
    /// Inline content for the required `input` artifact.
    #[arg(conflicts_with = "input_file")]
    pub content: Option<String>,
    /// Emit the created event without requesting autonomous pickup.
    #[arg(long)]
    pub silent: bool,
    /// Path to a file whose contents seed the required `input` artifact.
    #[arg(long, conflicts_with = "content")]
    pub input_file: Option<PathBuf>,
    /// Dependency slugs. Repeat the flag or pass comma-separated values.
    #[arg(long, action = ArgAction::Append, value_delimiter = ',')]
    pub after: Vec<String>,
    /// Work item kind. Defaults to `feature`.
    #[arg(long, default_value = "feature")]
    pub kind: String,
    /// Optional free-form description.
    #[arg(long)]
    pub description: Option<String>,
    /// Optional visual grouping label.
    #[arg(long)]
    pub group: Option<String>,
}

#[derive(Args, Debug)]
pub struct WorkflowUpdateArgs {
    /// Todo slug (unique per project).
    pub slug: String,
    /// Optional inline content to write as a new artifact version.
    pub content: Option<String>,
    /// Artifact kind for positional content. Defaults to `input`.
    #[arg(long)]
    pub artifact: Option<String>,
    /// Dependency slugs. Replaces the existing dependency set in full.
    #[arg(long, action = ArgAction::Append, value_delimiter = ',')]
    pub after: Vec<String>,
    /// New visual grouping label.
    #[arg(long)]
    pub group: Option<String>,
    /// New free-form description.
    #[arg(long)]
    pub description: Option<String>,
    /// New work item kind.
    #[arg(long)]
    pub kind: Option<String>,
    /// Write content as `implementation-plan` with the prepped HITL guard.
    #[arg(long)]
    pub prepped: bool,
}

#[derive(Args, Debug)]
pub struct WorkflowRenameArgs {
    /// Current todo slug.
    pub old_slug: String,
    /// New todo slug.
    pub new_slug: String,
}

#[derive(Args, Debug)]
pub struct WorkflowTodoDiffArgs {
    /// Todo slug (unique per project).
    pub slug: String,
}

#[derive(Args, Debug)]
pub struct WorkflowArtifactsArgs {
    #[command(subcommand)]
    pub command: WorkflowArtifactsCommand,
}

#[derive(Subcommand, Debug)]
pub enum WorkflowArtifactsCommand {
    /// Show a unified diff between two exact artifact versions.
    Diff(WorkflowArtifactDiffArgs),
}

#[derive(Args, Debug)]
pub struct WorkflowArtifactDiffArgs {
    /// Todo slug (unique per project).
    pub slug: String,
    /// Artifact kind.
    pub name: String,
    /// Digest of the older artifact version.
    pub old_digest: String,
    /// Digest of the newer artifact version.
    pub new_digest: String,
}

pub async fn dispatch(
    args: WorkflowArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    match args.command {
        WorkflowCommand::Todo(todo_args) => {
            dispatch_todo(todo_args, service, project, principal).await
        }
        WorkflowCommand::Artifacts(artifacts_args) => {
            dispatch_artifacts(artifacts_args, service, project).await
        }
    }
}

async fn dispatch_todo(
    args: WorkflowTodoArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    match args.command {
        WorkflowTodoCommand::Create(create_args) => {
            create_todo(create_args, service, project, principal).await
        }
        WorkflowTodoCommand::Update(update_args) => {
            update_todo(update_args, service, project, principal).await
        }
        WorkflowTodoCommand::Rename(rename_args) => {
            rename_todo(rename_args, service, project, principal).await
        }
        WorkflowTodoCommand::Diff(diff_args) => todo_diff(diff_args, service, project).await,
    }
}

async fn dispatch_artifacts(
    args: WorkflowArtifactsArgs,
    service: &WorkflowService,
    project: ProjectId,
) -> Result<i32> {
    match args.command {
        WorkflowArtifactsCommand::Diff(diff_args) => {
            artifacts_diff(diff_args, service, project).await
        }
    }
}

async fn create_todo(
    args: WorkflowCreateArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let after = parse_after_values(args.after.iter().map(String::as_str))?;
    let kind = parse_kind(&args.kind)?;
    let input_content = resolve_content(args.content.as_deref(), args.input_file.as_deref())?;
    let creation_mode = if args.silent {
        CreationMode::Silent
    } else {
        CreationMode::Pickup
    };

    let todo = service
        .create_todo(
            CreateTodoArgs {
                project,
                slug,
                kind,
                description: args.description,
                after,
                group: args.group,
                input_content,
                creation_mode,
            },
            principal,
        )
        .await?;
    output::print_json(&todo)?;
    Ok(0)
}

async fn update_todo(
    args: WorkflowUpdateArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    if args.prepped && args.content.is_none() {
        return Err(anyhow!("--prepped requires positional content"));
    }
    let artifact = args
        .artifact
        .as_deref()
        .map(parse_artifact_name)
        .transpose()?;
    let after = if args.after.is_empty() {
        None
    } else {
        Some(parse_after_values(args.after.iter().map(String::as_str))?)
    };
    let kind = args.kind.as_deref().map(parse_kind).transpose()?;

    let todo = service
        .update_todo(
            UpdateTodoArgs {
                project,
                slug,
                group: args.group.map(Some),
                description: args.description.map(Some),
                kind,
                after,
                content: args.content,
                artifact,
                prepped: args.prepped,
            },
            principal,
        )
        .await?;
    output::print_json(&todo)?;
    Ok(0)
}

async fn rename_todo(
    args: WorkflowRenameArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let old_slug = Slug::new(&args.old_slug).context("parse old todo slug")?;
    let new_slug = Slug::new(&args.new_slug).context("parse new todo slug")?;
    let outcome = service
        .rename_todo(project, &old_slug, new_slug, principal)
        .await?;
    println!(
        "renamed {} -> {} (rewritten_reference_count={})",
        outcome.old_slug.as_str(),
        outcome.new_slug.as_str(),
        outcome.rewritten_reference_count
    );
    Ok(0)
}

async fn todo_diff(
    args: WorkflowTodoDiffArgs,
    service: &WorkflowService,
    project: ProjectId,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let diff = service.todo_diff(project, &slug).await?;
    print_todo_diff(&diff);
    Ok(0)
}

async fn artifacts_diff(
    args: WorkflowArtifactDiffArgs,
    service: &WorkflowService,
    project: ProjectId,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse todo slug")?;
    let name = parse_artifact_name(&args.name)?;
    let diff = service
        .artifact_diff(project, &slug, name, &args.old_digest, &args.new_digest)
        .await?;
    print!("{}", diff.diff);
    Ok(0)
}

fn print_todo_diff(diff: &TodoDiff) {
    for diagnostic in &diff.diagnostics {
        println!("{diagnostic}");
    }
    for section in &diff.sections {
        if let Some(prefix) = &section.prefix {
            println!("{prefix}");
        }
        print!("{}", section.diff);
        if !section.diff.ends_with('\n') {
            println!();
        }
    }
}

fn resolve_content(inline: Option<&str>, file: Option<&Path>) -> Result<String> {
    match (inline, file) {
        (Some(_), Some(_)) => Err(anyhow!("content and --input-file are mutually exclusive")),
        (Some(content), None) => ensure_non_empty(content.to_owned()),
        (None, Some(path)) => {
            let content = std::fs::read_to_string(path)
                .with_context(|| format!("read input artifact from {}", path.display()))?;
            ensure_non_empty(content)
        }
        (None, None) => Err(anyhow!("content or --input-file is required")),
    }
}

fn ensure_non_empty(content: String) -> Result<String> {
    if content.trim().is_empty() {
        Err(anyhow!("input artifact content must not be empty"))
    } else {
        Ok(content)
    }
}
