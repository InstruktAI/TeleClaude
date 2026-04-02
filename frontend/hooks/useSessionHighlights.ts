"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AgentActivityEvent, SessionClosedEvent, SessionInfo } from "@/lib/api/types";
import { useWS } from "@/lib/ws/WebSocketProvider";
import { usePersistentState } from "@/hooks/usePersistentState";

const PREVIEW_HIGHLIGHT_DURATION_MS = 3_000;
const SESSION_HIGHLIGHTS_STORAGE_KEY = "teleclaude.chat.session-highlights";

type SessionHighlightType = "input" | "output";

interface PersistedHighlightState {
  highlightType?: SessionHighlightType;
  lastOutputSummary?: string | null;
  lastOutputSummaryAt?: string | null;
}

interface VolatileHighlightState {
  activityEvent?: string | null;
  activityText?: string | null;
}

export interface SessionHighlightViewState {
  highlightType?: SessionHighlightType | null;
  activityEvent?: string | null;
  activityText?: string | null;
  lastOutputSummary?: string | null;
  lastOutputSummaryAt?: string | null;
}

type PersistedHighlightMap = Record<string, PersistedHighlightState>;
type VolatileHighlightMap = Record<string, VolatileHighlightState>;

function sameViewState(
  left: SessionHighlightViewState | undefined,
  right: SessionHighlightViewState,
): boolean {
  return (
    left?.highlightType === right.highlightType &&
    left?.activityEvent === right.activityEvent &&
    left?.activityText === right.activityText &&
    left?.lastOutputSummary === right.lastOutputSummary &&
    left?.lastOutputSummaryAt === right.lastOutputSummaryAt
  );
}

function isToolUseEvent(
  event: AgentActivityEvent,
): event is Extract<AgentActivityEvent, { type: "tool_use" }> {
  return event.type === "tool_use";
}

function buildToolActivityText(
  event: Extract<AgentActivityEvent, { type: "tool_use" }>,
): string {
  if (!event.tool_name) return "";
  const preview = event.tool_preview ?? "";
  if (preview.startsWith(event.tool_name)) {
    const trimmed = preview.slice(event.tool_name.length).trimStart();
    return trimmed ? `${event.tool_name}: ${trimmed}` : event.tool_name;
  }
  return preview ? `${event.tool_name}: ${preview}` : event.tool_name;
}

function omitSession<T>(state: Record<string, T>, sessionId: string): Record<string, T> {
  if (!(sessionId in state)) return state;
  const next = { ...state };
  delete next[sessionId];
  return next;
}

export function useSessionHighlights(
  sessions: SessionInfo[],
  activeSessionId?: string | null,
) {
  const { onEvent } = useWS();
  const [persistedState, setPersistedState, persistence] =
    usePersistentState<PersistedHighlightMap>(
      SESSION_HIGHLIGHTS_STORAGE_KEY,
      {},
    );
  const [volatileState, setVolatileState] = useState<VolatileHighlightMap>({});
  const timersRef = useRef<Map<string, number>>(new Map());
  const activeSessionIdRef = useRef<string | null>(activeSessionId ?? null);
  const stableStateRef = useRef<Map<string, SessionHighlightViewState>>(new Map());
  activeSessionIdRef.current = activeSessionId ?? null;

  const cancelHighlightTimer = useCallback((sessionId: string) => {
    const timer = timersRef.current.get(sessionId);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timersRef.current.delete(sessionId);
    }
  }, []);

  const clearHighlightVisual = useCallback((sessionId: string) => {
    cancelHighlightTimer(sessionId);
    setPersistedState((prev) => {
      const entry = prev[sessionId];
      if (!entry?.highlightType) return prev;

      const nextEntry: PersistedHighlightState = { ...entry };
      delete nextEntry.highlightType;

      if (!nextEntry.lastOutputSummary && !nextEntry.lastOutputSummaryAt) {
        return omitSession(prev, sessionId);
      }

      return {
        ...prev,
        [sessionId]: nextEntry,
      };
    });
  }, [cancelHighlightTimer, setPersistedState]);

  const removeSessionState = useCallback((sessionId: string) => {
    cancelHighlightTimer(sessionId);
    setPersistedState((prev) => omitSession(prev, sessionId));
    setVolatileState((prev) => omitSession(prev, sessionId));
  }, [cancelHighlightTimer, setPersistedState]);

  const schedulePreviewClear = useCallback((sessionId: string) => {
    cancelHighlightTimer(sessionId);
    timersRef.current.set(
      sessionId,
      window.setTimeout(() => {
        timersRef.current.delete(sessionId);
        clearHighlightVisual(sessionId);
      }, PREVIEW_HIGHLIGHT_DURATION_MS),
    );
  }, [cancelHighlightTimer, clearHighlightVisual]);

  useEffect(() => {
    if (!persistence.isHydrated) return;

    const validSessionIds = new Set(sessions.map((session) => session.session_id));

    setPersistedState((prev) => {
      let changed = false;
      const next: PersistedHighlightMap = {};

      for (const session of sessions) {
        const previous = prev[session.session_id];
        const summary = session.last_output_summary ?? previous?.lastOutputSummary ?? null;
        const summaryAt =
          session.last_output_summary_at ?? previous?.lastOutputSummaryAt ?? null;
        const highlightType = previous?.highlightType;

        if (highlightType || summary || summaryAt) {
          next[session.session_id] = {
            ...(highlightType ? { highlightType } : {}),
            ...(summary ? { lastOutputSummary: summary } : {}),
            ...(summaryAt ? { lastOutputSummaryAt: summaryAt } : {}),
          };
        }

        if (
          previous?.highlightType !== highlightType ||
          previous?.lastOutputSummary !== summary ||
          previous?.lastOutputSummaryAt !== summaryAt
        ) {
          changed = true;
        }
      }

      if (!changed && Object.keys(prev).length === Object.keys(next).length) {
        return prev;
      }
      return next;
    });

    setVolatileState((prev) => {
      let changed = false;
      const next: VolatileHighlightMap = {};

      for (const [sessionId, value] of Object.entries(prev)) {
        if (!validSessionIds.has(sessionId)) {
          changed = true;
          cancelHighlightTimer(sessionId);
          continue;
        }
        next[sessionId] = value;
      }

      return changed ? next : prev;
    });
  }, [
    cancelHighlightTimer,
    persistence.isHydrated,
    sessions,
    setPersistedState,
  ]);

  useEffect(() => {
    if (!activeSessionId || !persistence.isHydrated) return;
    clearHighlightVisual(activeSessionId);
  }, [activeSessionId, clearHighlightVisual, persistence.isHydrated]);

  useEffect(() => {
    const cleanupClosed = onEvent("session_closed", (event) => {
      if (event.event !== "session_closed") return;
      removeSessionState((event as SessionClosedEvent).data.session_id);
    });

    const cleanupActivity = onEvent("agent_activity", (event) => {
      if (event.event !== "agent_activity") return;
      const activityEvent = event as AgentActivityEvent;
      const sessionId = activityEvent.session_id;

      setVolatileState((prev) => ({
        ...prev,
        [sessionId]: {
          activityEvent: activityEvent.type,
          activityText:
            isToolUseEvent(activityEvent)
              ? buildToolActivityText(activityEvent)
              : activityEvent.type === "agent_stop"
                ? activityEvent.summary ?? ""
                : "",
        },
      }));

      if (activityEvent.type === "user_prompt_submit") {
        setPersistedState((prev) => ({
          ...prev,
          [sessionId]: {
            ...prev[sessionId],
            highlightType: "input",
          },
        }));
        if (activeSessionIdRef.current === sessionId) {
          schedulePreviewClear(sessionId);
        }
        return;
      }

      if (activityEvent.type === "agent_stop") {
        setPersistedState((prev) => ({
          ...prev,
          [sessionId]: {
            ...prev[sessionId],
            highlightType: "output",
            lastOutputSummary:
              activityEvent.summary ?? prev[sessionId]?.lastOutputSummary ?? null,
            lastOutputSummaryAt:
              activityEvent.timestamp ??
              prev[sessionId]?.lastOutputSummaryAt ??
              null,
          },
        }));
        if (activeSessionIdRef.current === sessionId) {
          schedulePreviewClear(sessionId);
        }
      }
    });

    return () => {
      cleanupClosed();
      cleanupActivity();
    };
  }, [onEvent, removeSessionState, schedulePreviewClear, setPersistedState]);

  useEffect(() => {
    return () => {
      for (const timer of timersRef.current.values()) {
        window.clearTimeout(timer);
      }
      timersRef.current.clear();
    };
  }, []);

  return useMemo(() => {
    const sessionIds = new Set<string>([
      ...sessions.map((session) => session.session_id),
      ...Object.keys(persistedState),
      ...Object.keys(volatileState),
    ]);
    const next = new Map<string, SessionHighlightViewState>();
    const previous = stableStateRef.current;

    for (const sessionId of sessionIds) {
      const persisted = persistedState[sessionId];
      const volatile = volatileState[sessionId];
      const session = sessions.find((value) => value.session_id === sessionId);

      const state: SessionHighlightViewState = {
        highlightType: persisted?.highlightType ?? null,
        activityEvent: volatile?.activityEvent ?? null,
        activityText: volatile?.activityText ?? null,
        lastOutputSummary:
          persisted?.lastOutputSummary ?? session?.last_output_summary ?? null,
        lastOutputSummaryAt:
          persisted?.lastOutputSummaryAt ?? session?.last_output_summary_at ?? null,
      };

      if (
        state.highlightType ||
        state.activityEvent ||
        state.activityText ||
        state.lastOutputSummary ||
        state.lastOutputSummaryAt
      ) {
        const previousState = previous.get(sessionId);
        next.set(
          sessionId,
          previousState && sameViewState(previousState, state)
            ? previousState
            : state,
        );
      }
    }

    stableStateRef.current = next;
    return next;
  }, [persistedState, sessions, volatileState]);
}
