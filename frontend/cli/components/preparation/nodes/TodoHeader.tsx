/**
 * Header portion of a todo row: name, DOR score badge, and phase status badges.
 *
 * The DOR score badge is colored green (>= 8), yellow (>= 5), or red (< 5).
 * Phase badges render inline via TodoStatusBadge.
 *
 * Source: teleclaude/cli/tui/views/preparation.py (_render_todo, _build_status_block)
 */

import React from "react";
import { Box, Text } from "ink";

import { statusColor, themeText } from "@/lib/theme/ink-colors.js";
import type { TodoInfo } from "@/lib/api/types.js";

import { TodoStatusBadge } from "./TodoStatusBadge.js";
import type { PhaseStatus } from "./TodoStatusBadge.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TodoHeaderProps {
  /** The todo slug (display name) */
  slug: string;
  /** Todo data for status and phase information */
  todo: TodoInfo;
  /** Whether the parent node is expanded */
  isExpanded: boolean;
  /** Whether this row is selected */
  isSelected: boolean;
}

// ---------------------------------------------------------------------------
// Todo status label mapping (mirrors Python TodoStatus.display_label)
// ---------------------------------------------------------------------------

const STATUS_LABELS: Record<string, string> = {
  pending: "draft",
  ready: "ready",
  in_progress: "active",
};

function todoStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

function todoStatusColorFn(status: string): (text: string) => string {
  if (status === "ready") return statusColor("ready");
  if (status === "in_progress") return statusColor("warning");
  return themeText("secondary");
}

// ---------------------------------------------------------------------------
// DOR score color
// ---------------------------------------------------------------------------

function dorColorFn(score: number | null | undefined): (text: string) => string {
  if (score == null) return themeText("muted");
  if (score >= 8) return statusColor("ready");
  if (score >= 5) return statusColor("warning");
  return statusColor("error");
}

// ---------------------------------------------------------------------------
// Phase-aware status fields (mirrors Python _status_fields)
// ---------------------------------------------------------------------------

function isPhaseStarted(value: string | null | undefined): boolean {
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  return normalized !== "" && normalized !== "pending" && normalized !== "not_started" && normalized !== "-";
}

function isBuildActive(value: string | null | undefined): boolean {
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  const hidden = new Set(["pending", "not_started", "-", "complete", "completed", "approved", "done", "pass"]);
  return !hidden.has(normalized);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TodoHeader({ slug, todo, isExpanded, isSelected }: TodoHeaderProps) {
  const indicator = isExpanded ? "\u25BE" : "\u25B8"; // down/right triangle
  const statusLabel = todoStatusLabel(todo.status);
  const statusFmt = todoStatusColorFn(todo.status);

  const reviewStarted = isPhaseStarted(todo.review_status);
  const buildStarted = isPhaseStarted(todo.build_status);
  const buildActive = isBuildActive(todo.build_status);

  // Build the compact status block based on phase
  const renderStatusBlock = () => {
    // Review phase: show review + deferrals + findings
    if (reviewStarted) {
      const reviewValue = todo.review_status ?? "-";
      const defValue = todo.deferrals_status ?? "-";
      const findings = todo.findings_count >= 0 ? String(todo.findings_count) : "-";
      return (
        <Text>
          {statusFmt(statusLabel)}
          <Text>{themeText("secondary")(` r:${reviewValue} def:${defValue} f:${findings}`)}</Text>
        </Text>
      );
    }

    // Build phase: show build status
    if (buildActive) {
      const buildValue = todo.build_status ?? "-";
      return (
        <Text>
          {statusFmt(statusLabel)}
          <Text>{themeText("secondary")(` b:${buildValue}`)}</Text>
        </Text>
      );
    }

    // Pre-build: show DOR score
    if (!buildStarted) {
      const dorValue = todo.dor_score != null ? String(todo.dor_score) : "-";
      const dorFmt = dorColorFn(todo.dor_score);
      return (
        <Text>
          {statusFmt(statusLabel)}
          <Text>{themeText("muted")(" dor:")}</Text>
          <Text>{dorFmt(dorValue)}</Text>
        </Text>
      );
    }

    // Default: just the status label
    return <Text>{statusFmt(statusLabel)}</Text>;
  };

  return (
    <Box>
      <Text bold={isSelected} color={isSelected ? "yellow" : undefined}>
        {indicator} {slug}
      </Text>
      <Text> </Text>
      <Text>{themeText("muted")("[")}</Text>
      {renderStatusBlock()}
      <Text>{themeText("muted")("]")}</Text>
    </Box>
  );
}
