//! `telec roadmap` subtree.
//!
//! CRUD subcommands route through [`workflow::WorkflowService`];
//! `migrate-icebox` defers to v1 (filesystem-bound legacy helper).

use anyhow::{anyhow, Context, Result};
use clap::{Args, Subcommand};
use identity::Principal;
use shared::{ProjectId, Slug};
use workflow::WorkflowService;

use crate::output;
use crate::todo::EXIT_DEFERRED_TO_V1;

#[derive(Args, Debug)]
pub struct RoadmapArgs {
    #[command(subcommand)]
    pub command: RoadmapCommand,
}

#[derive(Subcommand, Debug)]
pub enum RoadmapCommand {
    /// List roadmap entries (source of truth for todo status).
    List(ListArgs),
    /// Add an entry to the roadmap.
    Add(AddArgs),
    /// Remove an entry from the roadmap.
    Remove(SlugArgs),
    /// Reorder an entry in the roadmap.
    Move(MoveArgs),
    /// Set dependencies for an entry.
    Deps(DepsArgs),
    /// Move an entry to the icebox.
    Freeze(SlugArgs),
    /// Promote an entry from the icebox to the active roadmap.
    Unfreeze(SlugArgs),
    /// Migrate v1 icebox folders into `todos/_icebox/` (deferred to v1).
    MigrateIcebox,
    /// Mark an entry as delivered.
    Deliver(DeliverArgs),
}

#[derive(Args, Debug)]
pub struct ListArgs {
    /// Include icebox entries in the listing.
    #[arg(long)]
    pub include_icebox: bool,
    /// Show only icebox entries.
    #[arg(long)]
    pub icebox_only: bool,
    /// Include delivered entries in the listing.
    #[arg(long)]
    pub include_delivered: bool,
    /// Show only delivered entries.
    #[arg(long)]
    pub delivered_only: bool,
    /// Emit results as JSON instead of a table.
    #[arg(long)]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct AddArgs {
    pub slug: String,
    /// Visual grouping label.
    #[arg(long)]
    pub group: Option<String>,
    /// Comma-separated dependency slugs.
    #[arg(long)]
    pub after: Option<String>,
    /// Insert before this slug (default: append).
    #[arg(long)]
    pub before: Option<String>,
    /// Summary description.
    #[arg(long)]
    pub description: Option<String>,
}

#[derive(Args, Debug)]
pub struct SlugArgs {
    pub slug: String,
}

#[derive(Args, Debug)]
pub struct MoveArgs {
    pub slug: String,
    /// Move before this slug.
    #[arg(long)]
    pub before: Option<String>,
    /// Move after this slug.
    #[arg(long)]
    pub after: Option<String>,
}

#[derive(Args, Debug)]
pub struct DepsArgs {
    pub slug: String,
    /// Comma-separated dependency slugs (replaces existing edges verbatim).
    #[arg(long, default_value = "")]
    pub after: String,
}

#[derive(Args, Debug)]
pub struct DeliverArgs {
    pub slug: String,
    /// Commit hash to record (auto-detection is not implemented in v2; pass
    /// the hash explicitly).
    #[arg(long)]
    pub commit: Option<String>,
}

/// Dispatch a parsed `telec roadmap` invocation against the workflow service.
pub async fn dispatch(
    args: RoadmapArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    match args.command {
        RoadmapCommand::List(a) => list(a, service, project).await,
        RoadmapCommand::Add(a) => add(a, service, project, principal).await,
        RoadmapCommand::Remove(a) => remove(a, service, project, principal).await,
        RoadmapCommand::Move(a) => move_entry(a, service, project, principal).await,
        RoadmapCommand::Deps(a) => deps(a, service, project, principal).await,
        RoadmapCommand::Freeze(a) => freeze(a, service, project, principal).await,
        RoadmapCommand::Unfreeze(a) => unfreeze(a, service, project, principal).await,
        RoadmapCommand::MigrateIcebox => migrate_icebox(),
        RoadmapCommand::Deliver(a) => deliver(a, service, project, principal).await,
    }
}

async fn list(args: ListArgs, service: &WorkflowService, project: ProjectId) -> Result<i32> {
    // Translate the v1 flag combinations to the service surface:
    // - icebox_only → include_icebox=true; results filtered post-fetch to
    //   icebox rows.
    // - delivered_only → include_delivered=true; results filtered to
    //   delivered rows.
    let include_icebox = args.include_icebox || args.icebox_only;
    let include_delivered = args.include_delivered || args.delivered_only;
    let mut entries = service
        .list_roadmap(project, include_icebox, include_delivered)
        .await?;

    if args.icebox_only {
        entries.retain(|e| e.frozen);
    } else if args.delivered_only {
        entries.retain(|e| e.delivered_at.is_some());
    }

    if args.json {
        output::print_json(&entries)?;
    } else {
        println!("{}", output::render_roadmap(&entries));
    }
    Ok(0)
}

async fn add(
    args: AddArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse roadmap slug")?;
    let after = parse_after(args.after.as_deref())?;
    let before = match args.before {
        Some(b) => Some(Slug::new(&b).context("parse --before slug")?),
        None => None,
    };
    let entry = service
        .add_roadmap_entry(
            project,
            slug,
            args.group,
            after,
            before,
            args.description,
            principal,
        )
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

async fn remove(
    args: SlugArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse roadmap slug")?;
    service
        .remove_roadmap_entry(project, &slug, principal)
        .await?;
    println!("removed roadmap entry {}", slug.as_str());
    Ok(0)
}

async fn move_entry(
    args: MoveArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    if args.before.is_some() == args.after.is_some() {
        return Err(anyhow!("move requires exactly one of --before or --after"));
    }
    let slug = Slug::new(&args.slug).context("parse roadmap slug")?;
    let before = match args.before {
        Some(b) => Some(Slug::new(&b).context("parse --before slug")?),
        None => None,
    };
    let after = match args.after {
        Some(a) => Some(Slug::new(&a).context("parse --after slug")?),
        None => None,
    };
    let entry = service
        .move_roadmap_entry(project, &slug, before, after, principal)
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

async fn deps(
    args: DepsArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse roadmap slug")?;
    let after = parse_after(Some(&args.after))?;
    // Roadmap deps live alongside todo deps; updating the todo cascades to
    // both the todo row, the roadmap entry, and the `roadmap_deps` edges.
    let patch = workflow::TodoPatch {
        after: Some(after),
        ..Default::default()
    };
    let todo = service
        .update_todo(project, &slug, patch, principal)
        .await?;
    output::print_json(&todo)?;
    Ok(0)
}

async fn freeze(
    args: SlugArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse roadmap slug")?;
    let entry = service
        .freeze_roadmap_entry(project, &slug, principal)
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

async fn unfreeze(
    args: SlugArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse roadmap slug")?;
    let entry = service
        .unfreeze_roadmap_entry(project, &slug, principal)
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

async fn deliver(
    args: DeliverArgs,
    service: &WorkflowService,
    project: ProjectId,
    principal: &Principal,
) -> Result<i32> {
    let slug = Slug::new(&args.slug).context("parse roadmap slug")?;
    let entry = service
        .deliver_roadmap_entry(project, &slug, args.commit, principal)
        .await?;
    output::print_json(&entry)?;
    Ok(0)
}

fn migrate_icebox() -> Result<i32> {
    eprintln!(
        "telec roadmap migrate-icebox: not implemented in v2-mvp (filesystem-bound legacy \
         helper); falls back to v1 Python implementation."
    );
    Ok(EXIT_DEFERRED_TO_V1)
}

fn parse_after(raw: Option<&str>) -> Result<Vec<Slug>> {
    let Some(raw) = raw else {
        return Ok(Vec::new());
    };
    raw.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(Slug::new)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| anyhow!("invalid dependency slug: {err}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_after_splits_on_comma() {
        let after = parse_after(Some("alpha,beta")).expect("parse");
        assert_eq!(
            after.iter().map(Slug::as_str).collect::<Vec<_>>(),
            vec!["alpha", "beta"],
        );
    }

    #[test]
    fn parse_after_handles_blank_input() {
        assert!(parse_after(Some("  ")).expect("parse").is_empty());
        assert!(parse_after(None).expect("parse").is_empty());
    }
}
