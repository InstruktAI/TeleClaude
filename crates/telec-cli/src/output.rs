//! Output helpers — table rendering plus JSON emission.
//!
//! Centralizing the formatting choices here keeps subcommand handlers
//! focused on data assembly and lets snapshot tests lock the layout.

use anyhow::{Context, Result};
use serde::Serialize;
use tabled::settings::Style;
use tabled::{Table, Tabled};
use workflow::models::RoadmapEntry;

/// Pretty-print a serializable value as indented JSON to stdout.
pub fn print_json<T: Serialize>(value: &T) -> Result<()> {
    let rendered = serde_json::to_string_pretty(value).context("serialize JSON")?;
    println!("{rendered}");
    Ok(())
}

/// Render a list of roadmap entries as an aligned table.
pub fn render_roadmap(entries: &[RoadmapEntry]) -> String {
    let rows: Vec<RoadmapRow> = entries.iter().map(RoadmapRow::from_entry).collect();
    Table::new(rows).with(Style::sharp()).to_string()
}

#[derive(Tabled)]
struct RoadmapRow {
    position: i32,
    slug: String,
    group: String,
    frozen: bool,
    delivered: bool,
    after: String,
}

impl RoadmapRow {
    fn from_entry(entry: &RoadmapEntry) -> Self {
        Self {
            position: entry.position,
            slug: entry.slug.as_str().to_owned(),
            group: entry.group.clone().unwrap_or_default(),
            frozen: entry.frozen,
            delivered: entry.delivered_at.is_some(),
            after: entry
                .after
                .iter()
                .map(|s| s.as_str().to_owned())
                .collect::<Vec<_>>()
                .join(","),
        }
    }
}
