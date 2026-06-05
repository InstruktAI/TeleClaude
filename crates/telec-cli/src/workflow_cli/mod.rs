//! `telec workflow` subtree.
//!
//! This namespace hosts v2-native workflow operations that do not belong to
//! the legacy-compatible `telec todo` transition surface.

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use clap::{ArgAction, Args, Subcommand};
use identity::Principal;
use shared::{ProjectId, Slug};
use workflow::models::CreationMode;
use workflow::service::CreateTodoArgs;
use workflow::WorkflowService;

use crate::output;
use crate::todo::{parse_after_values, parse_kind};

#[derive(Args, Debug)]
pub struct WorkflowArgs {
    #[command(subcommand)]
    pub command: WorkflowCommand,
}

#[derive(Subcommand, Debug)]
pub enum WorkflowCommand {
    /// Manage workflow todos.
    Todo(WorkflowTodoArgs),
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
    /// Work item kind: feature | change | bug.
    #[arg(long)]
    pub kind: String,
    /// Optional free-form description.
    #[arg(long)]
    pub description: Option<String>,
    /// Optional visual grouping label.
    #[arg(long)]
    pub group: Option<String>,
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
