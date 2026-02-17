/**
 * View router that renders the active tab's content.
 *
 * Dispatches to the real view components: SessionsView, PreparationView,
 * and ConfigurationView.
 */

import React from "react";
import { Box } from "ink";

import { SessionsView } from "../sessions/SessionsView.js";
import { PreparationView } from "../preparation/PreparationView.js";
import { ConfigurationView } from "../configuration/ConfigurationView.js";
import type { TelecAPIClient } from "@/lib/api/client.js";
import type {
  ComputerInfo,
  ProjectInfo,
  ProjectWithTodosInfo,
  SessionInfo,
} from "@/lib/api/types.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ViewContainerProps {
  activeTab: "sessions" | "preparation" | "configuration";
  api: TelecAPIClient;
  computers: ComputerInfo[];
  projects: ProjectInfo[];
  sessions: SessionInfo[];
  projectsWithTodos: ProjectWithTodosInfo[];
  viewportHeight?: number;
  onNewSession?: () => void;
  onEndSession?: (sessionId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ViewContainer({
  activeTab,
  api,
  computers,
  projects,
  sessions,
  projectsWithTodos,
  viewportHeight,
  onNewSession,
  onEndSession,
}: ViewContainerProps) {
  switch (activeTab) {
    case "sessions":
      return (
        <Box flexDirection="column">
          <SessionsView
            computers={computers}
            projects={projects}
            sessions={sessions}
            viewportHeight={viewportHeight}
            onNewSession={onNewSession}
            onEndSession={onEndSession}
          />
        </Box>
      );

    case "preparation":
      return (
        <Box flexDirection="column">
          <PreparationView
            projects={projectsWithTodos}
            viewportHeight={viewportHeight}
          />
        </Box>
      );

    case "configuration":
      return (
        <Box flexDirection="column">
          <ConfigurationView api={api} />
        </Box>
      );
  }
}
