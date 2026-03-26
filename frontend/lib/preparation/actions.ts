import type { TodoInfo } from "@/lib/api/types";

export type PreparationSelectionKind = "computer" | "project" | "todo" | "file";

export type PreparationActionReason =
  | "selection_required"
  | "daemon_endpoint_unavailable";

export interface PreparationActionState {
  enabled: boolean;
  reason?: PreparationActionReason;
}

export interface PreparationActionAvailability {
  prepare: PreparationActionState;
  startWork: PreparationActionState;
  refine: PreparationActionState;
  remove: PreparationActionState;
  freeze: PreparationActionState;
  moveUp: PreparationActionState;
  moveDown: PreparationActionState;
}

export interface PreparationActionAvailabilityInput {
  kind: PreparationSelectionKind;
  todo?: TodoInfo;
}

function selectableAction(enabled: boolean): PreparationActionState {
  return enabled
    ? { enabled: true }
    : { enabled: false, reason: "selection_required" };
}

export function getPreparationActionAvailability(
  input: PreparationActionAvailabilityInput,
): PreparationActionAvailability {
  const hasTodoSelection = input.kind === "todo" && input.todo !== undefined;

  return {
    prepare: selectableAction(hasTodoSelection),
    startWork: selectableAction(hasTodoSelection),
    refine: selectableAction(hasTodoSelection),
    remove: hasTodoSelection
      ? { enabled: false, reason: "daemon_endpoint_unavailable" }
      : selectableAction(false),
    freeze: hasTodoSelection
      ? { enabled: false, reason: "daemon_endpoint_unavailable" }
      : selectableAction(false),
    moveUp: hasTodoSelection
      ? { enabled: false, reason: "daemon_endpoint_unavailable" }
      : selectableAction(false),
    moveDown: hasTodoSelection
      ? { enabled: false, reason: "daemon_endpoint_unavailable" }
      : selectableAction(false),
  };
}
