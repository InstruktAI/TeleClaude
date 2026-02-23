/**
 * Root application component for the TeleClaude terminal UI.
 *
 * Orchestrates the vertical layout (AnimatedBanner, TabBar, ViewContainer,
 * Footer), manages WebSocket lifecycle, background timers, persistence,
 * modal overlays, and initial data fetching.
 *
 * Data flow:
 *   WebSocket -> Store (via useWebSocket dispatch)
 *   Store -> Views (via useTuiStore selectors)
 *   Keys -> Store (via useKeyBindings action dispatch)
 *   Store -> Persistence (debounced save on subscribe)
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Box, useApp } from "ink";

import { TelecAPIClient } from "@/lib/api/client.js";
import type {
  ComputerInfo,
  ProjectInfo,
  ProjectWithTodosInfo,
  SessionInfo,
  AgentAvailabilityInfo,
  CreateSessionRequest,
} from "@/lib/api/types.js";
import { useTuiStore, tuiStore } from "@/lib/store/index.js";
import { launchSession } from "@/lib/session/launcher.js";
import type { ViewContext } from "@/lib/keys/types.js";

import { useWebSocket } from "./hooks/useWebSocket.js";
import { useKeyBindings } from "./hooks/useKeyBindings.js";
import { useTimers } from "./hooks/useTimers.js";

import { AnimatedBanner } from "./components/animation/AnimatedBanner.js";
import { TabBar } from "./components/layout/TabBar.js";
import { ViewContainer } from "./components/layout/ViewContainer.js";
import { Footer } from "./components/layout/Footer.js";
import { Notification } from "./components/layout/Notification.js";
import { StartSessionModal } from "./components/modals/StartSessionModal.js";
import { ConfirmModal } from "./components/modals/ConfirmModal.js";

import {
  loadTuiState,
  saveTuiState,
  type PersistedTuiState,
} from "./lib/persistence.js";

// ---------------------------------------------------------------------------
// Tab name mapping
// ---------------------------------------------------------------------------

const TAB_NAMES = ["sessions", "preparation", "configuration"] as const;
type TabName = (typeof TAB_NAMES)[number];

// ---------------------------------------------------------------------------
// Debounced persistence subscriber
// ---------------------------------------------------------------------------

function createDebouncedPersister(delayMs: number) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  return () => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      const state = tuiStore.getState();
      const persisted: PersistedTuiState = {
        stickySessionIds: state.sessions.stickySessions.map((s) => s.sessionId),
        collapsedSessions: Array.from(state.sessions.collapsedSessions),
        inputHighlights: Array.from(state.sessions.inputHighlights),
        outputHighlights: Array.from(state.sessions.outputHighlights),
        lastOutputSummaries: state.sessions.lastOutputSummary,
        expandedTodos: Array.from(state.preparation.expandedTodos),
        previewSessionId: state.sessions.preview?.sessionId ?? null,
        animationMode: state.animationMode,
      };
      saveTuiState(persisted);
    }, delayMs);
  };
}

// ---------------------------------------------------------------------------
// Viewport height calculation
// ---------------------------------------------------------------------------

const BANNER_HEIGHT = 6; // 5 lines + 1 padding
const TAB_BAR_HEIGHT = 2; // tabs + separator
const FOOTER_HEIGHT = 3; // separator + hints + status

function getViewportHeight(): number {
  const termRows = process.stdout?.rows ?? 24;
  return Math.max(5, termRows - BANNER_HEIGHT - TAB_BAR_HEIGHT - FOOTER_HEIGHT);
}

// ---------------------------------------------------------------------------
// Root App
// ---------------------------------------------------------------------------

export function App() {
  const app = useApp();
  const dispatch = useTuiStore((s) => s.dispatch);

  // -- API client (stable across renders) -----------------------------------

  const api = useMemo(() => new TelecAPIClient(), []);

  // -- Tab state ------------------------------------------------------------

  const [activeTab, setActiveTab] = useState<TabName>("sessions");

  // -- Notification state ---------------------------------------------------

  const [notification, setNotification] = useState<{
    message: string;
    type: "info" | "error" | "success";
  } | null>(null);

  const showNotification = useCallback(
    (message: string, type: "info" | "error" | "success" = "info") => {
      setNotification({ message, type });
    },
    [],
  );

  const dismissNotification = useCallback(() => {
    setNotification(null);
  }, []);

  // -- Domain data ----------------------------------------------------------

  const [computers, setComputers] = useState<ComputerInfo[]>([]);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [projectsWithTodos, setProjectsWithTodos] = useState<ProjectWithTodosInfo[]>([]);
  const [agentAvailability, setAgentAvailability] = useState<
    Record<string, AgentAvailabilityInfo>
  >({});

  // -- Modal state ----------------------------------------------------------

  const [startSessionModalOpen, setStartSessionModalOpen] = useState(false);
  const [confirmEndSession, setConfirmEndSession] = useState<{
    sessionId: string;
    title: string;
  } | null>(null);

  // -- Viewport height (recalculated on resize) -----------------------------

  const [viewportHeight, setViewportHeight] = useState(getViewportHeight);

  useEffect(() => {
    const onResize = () => setViewportHeight(getViewportHeight());
    process.stdout?.on("resize", onResize);
    return () => {
      process.stdout?.off("resize", onResize);
    };
  }, []);

  // -- WebSocket lifecycle (daemon connection) ------------------------------

  const { connected, error: wsError } = useWebSocket();

  useEffect(() => {
    if (wsError) {
      showNotification(wsError, "error");
    }
  }, [wsError, showNotification]);

  // -- Background timers (streaming safety, viewing inactivity, heal) -------

  useTimers();

  // -- Load persisted state on mount ----------------------------------------

  const persistenceInitialized = useRef(false);

  useEffect(() => {
    if (persistenceInitialized.current) return;
    persistenceInitialized.current = true;

    const persisted = loadTuiState();

    // Apply persisted sticky sessions
    for (const sessionId of persisted.stickySessionIds) {
      dispatch({ type: "TOGGLE_STICKY", sessionId });
    }
    // Apply persisted collapsed sessions
    for (const sessionId of persisted.collapsedSessions) {
      dispatch({ type: "COLLAPSE_SESSION", sessionId });
    }
    // Apply persisted expanded todos
    for (const todoId of persisted.expandedTodos) {
      dispatch({ type: "EXPAND_TODO", todoId });
    }
    // Apply animation mode
    if (persisted.animationMode) {
      dispatch({ type: "SET_ANIMATION_MODE", mode: persisted.animationMode });
    }
    // Apply preview
    if (persisted.previewSessionId) {
      dispatch({ type: "SET_PREVIEW", sessionId: persisted.previewSessionId });
    }
  }, [dispatch]);

  // -- Subscribe to store changes for debounced persistence -----------------

  useEffect(() => {
    const debouncedPersist = createDebouncedPersister(1000);
    const unsubscribe = tuiStore.subscribe(debouncedPersist);
    return unsubscribe;
  }, []);

  // -- Initial data fetch ---------------------------------------------------

  const fetchData = useCallback(async () => {
    try {
      const [computersData, projectsData, sessionsData, todosData, agentData] =
        await Promise.all([
          api.getComputers().catch(() => [] as ComputerInfo[]),
          api.getProjects().catch(() => [] as ProjectInfo[]),
          api.getSessions().catch(() => [] as SessionInfo[]),
          api.getProjectsWithTodos().catch(() => [] as ProjectWithTodosInfo[]),
          api.getAgentAvailability().catch(
            () => ({}) as Record<string, AgentAvailabilityInfo>,
          ),
        ]);

      setComputers(computersData);
      setProjects(projectsData);
      setSessions(sessionsData);
      setProjectsWithTodos(todosData);
      setAgentAvailability(agentData);

      // Sync session IDs to store
      const sessionIds = sessionsData.map((s) => s.session_id);
      dispatch({ type: "SYNC_SESSIONS", sessionIds });

      // Sync todo IDs to store
      const todoIds = todosData.flatMap((p) => p.todos.map((t) => t.slug));
      if (todoIds.length > 0) {
        dispatch({ type: "SYNC_TODOS", todoIds });
      }
    } catch {
      // Individual fetches are already caught above
    }
  }, [api, dispatch]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Re-fetch when WebSocket delivers session updates
  useEffect(() => {
    if (!connected) return;

    const unsubscribe = tuiStore.subscribe((state, prevState) => {
      // When SYNC_SESSIONS fires from WebSocket handler, refresh domain data
      const curIds = state.sessions.selectedSessionId;
      const prevIds = prevState.sessions.selectedSessionId;
      if (curIds !== prevIds) {
        // Lightweight re-fetch of sessions to keep local state in sync
        api
          .getSessions()
          .then(setSessions)
          .catch(() => {});
      }
    });

    return unsubscribe;
  }, [connected, api]);

  // Re-fetch projectsWithTodos when WebSocket delivers todo updates
  const todosRefreshTrigger = useTuiStore(
    (s) => s.preparation.todosRefreshTrigger,
  );

  useEffect(() => {
    if (todosRefreshTrigger === 0) return; // Skip initial render
    api
      .getProjectsWithTodos()
      .then(setProjectsWithTodos)
      .catch(() => {});
  }, [todosRefreshTrigger, api]);

  // -- Session creation handler ---------------------------------------------

  const handleCreateSession = useCallback(
    async (request: CreateSessionRequest) => {
      setStartSessionModalOpen(false);
      showNotification("Starting session...", "info");

      const result = await launchSession({
        computer: request.computer,
        projectPath: request.project_path,
        agent: request.agent ?? "claude",
        thinkingMode: request.thinking_mode ?? "slow",
        title: request.title ?? undefined,
        message: request.message ?? undefined,
      });

      if (result.success) {
        showNotification("Session started", "success");
        // Re-fetch sessions to include the new one
        api
          .getSessions()
          .then((updated) => {
            setSessions(updated);
            const ids = updated.map((s) => s.session_id);
            dispatch({ type: "SYNC_SESSIONS", sessionIds: ids });
          })
          .catch(() => {});
      } else {
        showNotification(result.error ?? "Failed to start session", "error");
      }
    },
    [api, dispatch, showNotification],
  );

  // -- Session end handler --------------------------------------------------

  const handleEndSession = useCallback(
    (sessionId: string) => {
      const session = sessions.find((s) => s.session_id === sessionId);
      setConfirmEndSession({
        sessionId,
        title: session?.title || sessionId.slice(0, 8),
      });
    },
    [sessions],
  );

  const confirmEndSessionHandler = useCallback(async () => {
    if (!confirmEndSession) return;
    const { sessionId } = confirmEndSession;
    setConfirmEndSession(null);
    showNotification("Ending session...", "info");

    try {
      const session = sessions.find((s) => s.session_id === sessionId);
      await api.endSession(sessionId, session?.computer ?? "local");
      showNotification("Session ended", "success");

      // Re-fetch
      const updated = await api.getSessions();
      setSessions(updated);
      const ids = updated.map((s) => s.session_id);
      dispatch({ type: "SYNC_SESSIONS", sessionIds: ids });
    } catch {
      showNotification("Failed to end session", "error");
    }
  }, [confirmEndSession, sessions, api, dispatch, showNotification]);

  // -- Global key handling (tab switching, quit, refresh, animation mode) ---

  const isModalOpen = startSessionModalOpen || confirmEndSession !== null;

  useKeyBindings(
    isModalOpen ? "global" : (activeTab as ViewContext),
    isModalOpen
      ? {}
      : {
          quit: () => app.exit(),
          tab_sessions: () => setActiveTab("sessions"),
          tab_preparation: () => setActiveTab("preparation"),
          tab_configuration: () => setActiveTab("configuration"),
          refresh: () => {
            showNotification("Refreshing...", "info");
            fetchData();
          },
          cycle_animation: () => {
            const modes = ["periodic", "party", "off"] as const;
            const current = useTuiStore.getState().animationMode;
            const idx = modes.indexOf(current);
            const next = modes[(idx + 1) % modes.length];
            dispatch({ type: "SET_ANIMATION_MODE", mode: next });
            showNotification(`Animation: ${next.toUpperCase()}`, "info");
          },
        },
  );

  // -- Derive view context for footer hints ---------------------------------

  const viewContext: ViewContext = activeTab;

  // -- Render ---------------------------------------------------------------

  return (
    <Box flexDirection="column" height="100%">
      <AnimatedBanner />
      <TabBar activeTab={activeTab} />
      {notification && (
        <Notification
          message={notification.message}
          type={notification.type}
          onDismiss={dismissNotification}
        />
      )}
      <Box flexGrow={1}>
        <ViewContainer
          activeTab={activeTab}
          api={api}
          computers={computers}
          projects={projects}
          sessions={sessions}
          projectsWithTodos={projectsWithTodos}
          viewportHeight={viewportHeight}
          onNewSession={() => setStartSessionModalOpen(true)}
          onEndSession={handleEndSession}
        />
      </Box>
      <Footer viewContext={viewContext} connected={connected} />

      {/* Modals rendered as overlays */}
      {startSessionModalOpen && (
        <StartSessionModal
          computers={computers}
          projects={projects}
          agentAvailability={agentAvailability}
          onSubmit={handleCreateSession}
          onCancel={() => setStartSessionModalOpen(false)}
        />
      )}
      {confirmEndSession && (
        <ConfirmModal
          title="End Session"
          message={`End session "${confirmEndSession.title}"?`}
          details={[`ID: ${confirmEndSession.sessionId}`]}
          confirmLabel="End"
          cancelLabel="Cancel"
          onConfirm={confirmEndSessionHandler}
          onCancel={() => setConfirmEndSession(null)}
        />
      )}
    </Box>
  );
}
