//! Help-text smoke tests for the `telec-cli` binary.
//!
//! These run unconditionally and require no Postgres / Redis. They lock the
//! public CLI surface by snapshotting the `Commands:` section of each
//! `--help` rendering. Snapshots — not substring `contains()` checks — are
//! the canonical assertion shape per the project's testing policy
//! (reviewer Important-3).

use assert_cmd::Command;

fn telec() -> Command {
    Command::cargo_bin("telec-cli").expect("locate telec-cli binary")
}

fn help_subcommand_section(args: &[&str]) -> String {
    let mut cmd = telec();
    cmd.args(args);
    let output = cmd.output().expect("run telec-cli --help");
    assert!(
        output.status.success(),
        "non-zero exit from telec-cli {args:?} --help"
    );
    let stdout = String::from_utf8(output.stdout).expect("utf-8 stdout");
    extract_section(&stdout, "Commands:", "Options:")
}

#[test]
fn top_level_help_subcommand_list_snapshot() {
    let extracted = help_subcommand_section(&["--help"]);
    insta::assert_snapshot!("top_level_commands", extracted);
}

#[test]
fn todo_help_subcommand_list_snapshot() {
    let extracted = help_subcommand_section(&["todo", "--help"]);
    insta::assert_snapshot!("todo_commands", extracted);
}

#[test]
fn roadmap_help_subcommand_list_snapshot() {
    let extracted = help_subcommand_section(&["roadmap", "--help"]);
    insta::assert_snapshot!("roadmap_commands", extracted);
}

fn extract_section(text: &str, start_marker: &str, end_marker: &str) -> String {
    let mut collecting = false;
    let mut buf = String::new();
    for line in text.lines() {
        if line.trim_start().starts_with(start_marker) {
            collecting = true;
            continue;
        }
        if collecting && line.trim_start().starts_with(end_marker) {
            break;
        }
        if collecting {
            buf.push_str(line.trim_end());
            buf.push('\n');
        }
    }
    buf
}
