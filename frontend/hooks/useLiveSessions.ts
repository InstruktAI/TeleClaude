'use client';

import { useEffect, useState } from 'react';
import type {
  SessionClosedEvent,
  SessionInfo,
  SessionStartedEvent,
  SessionStatusEvent,
  SessionsInitialEvent,
  SessionUpdatedEvent,
} from '@/lib/api/types';
import { useSessions } from '@/lib/hooks/useSessions';
import { useWS } from '@/lib/ws/WebSocketProvider';

const HIDDEN_SESSION_STATUSES = new Set(['closing', 'closed']);

function matchesComputer(session: Pick<SessionInfo, 'computer'>, computer?: string): boolean {
  if (!computer) return true;
  return session.computer === computer;
}

function upsertSession(sessions: SessionInfo[], nextSession: SessionInfo, computer?: string): SessionInfo[] {
  if (!matchesComputer(nextSession, computer)) {
    return sessions;
  }

  if (HIDDEN_SESSION_STATUSES.has(nextSession.status)) {
    return sessions.filter((session) => session.session_id !== nextSession.session_id);
  }

  const index = sessions.findIndex((session) => session.session_id === nextSession.session_id);
  if (index === -1) {
    return [...sessions, nextSession];
  }

  const next = sessions.slice();
  next[index] = nextSession;
  return next;
}

function removeSession(sessions: SessionInfo[], sessionId: string): SessionInfo[] {
  return sessions.filter((session) => session.session_id !== sessionId);
}

function patchSessionStatus(sessions: SessionInfo[], event: SessionStatusEvent): SessionInfo[] {
  let changed = false;
  const next = sessions.map((session) => {
    if (session.session_id !== event.session_id) return session;
    if (session.status === event.status) return session;
    changed = true;
    return {
      ...session,
      status: event.status,
    };
  });
  return changed ? next : sessions;
}

export function useLiveSessions(computer?: string) {
  const query = useSessions(computer);
  const { onEvent } = useWS();
  const [sessions, setSessions] = useState<SessionInfo[]>(() => query.data ?? []);
  const [prevQueryData, setPrevQueryData] = useState(query.data);
  const [prevQueryIsLoading, setPrevQueryIsLoading] = useState(query.isLoading);

  if (query.data !== prevQueryData || query.isLoading !== prevQueryIsLoading) {
    setPrevQueryData(query.data);
    setPrevQueryIsLoading(query.isLoading);
    if (query.data) {
      setSessions(query.data);
    } else if (!query.isLoading) {
      setSessions([]);
    }
  }

  useEffect(() => {
    const cleanupInitial = onEvent('sessions_initial', (event) => {
      if (event.event !== 'sessions_initial') return;
      const initialEvent = event as SessionsInitialEvent;
      if (computer && initialEvent.data.computer && initialEvent.data.computer !== computer) {
        return;
      }
      setSessions(initialEvent.data.sessions);
    });

    const cleanupStarted = onEvent('session_started', (event) => {
      if (event.event !== 'session_started') return;
      const startedEvent = event as SessionStartedEvent;
      setSessions((prev) => upsertSession(prev, startedEvent.data, computer));
    });

    const cleanupUpdated = onEvent('session_updated', (event) => {
      if (event.event !== 'session_updated') return;
      const updatedEvent = event as SessionUpdatedEvent;
      setSessions((prev) => upsertSession(prev, updatedEvent.data, computer));
    });

    const cleanupClosed = onEvent('session_closed', (event) => {
      if (event.event !== 'session_closed') return;
      const closedEvent = event as SessionClosedEvent;
      setSessions((prev) => removeSession(prev, closedEvent.data.session_id));
    });

    const cleanupStatus = onEvent('session_status', (event) => {
      if (event.event !== 'session_status') return;
      setSessions((prev) => patchSessionStatus(prev, event as SessionStatusEvent));
    });

    return () => {
      cleanupInitial();
      cleanupStarted();
      cleanupUpdated();
      cleanupClosed();
      cleanupStatus();
    };
  }, [computer, onEvent]);

  return {
    data: sessions,
    isLoading: query.isLoading && query.data === undefined && sessions.length === 0,
    error: query.error,
    refetch: query.refetch,
  };
}
