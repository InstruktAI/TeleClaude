"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface Session {
  session_id: string;
  computer: string;
  status?: string;
  created_at?: string;
}

export function SessionPicker() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/sessions")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        const list = Array.isArray(data) ? data : data.sessions ?? [];
        setSessions(list);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading sessions...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-destructive">Failed to load sessions: {error}</p>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">No active sessions found.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
      <h2 className="text-lg font-semibold">Select a session</h2>
      <div className="flex w-full max-w-md flex-col gap-2">
        {sessions.map((s) => (
          <button
            key={s.session_id}
            onClick={() => router.push(`/?sessionId=${s.session_id}`)}
            className="rounded-lg border bg-card px-4 py-3 text-left text-sm transition-colors hover:bg-accent"
          >
            <span className="font-medium">{s.session_id.slice(0, 8)}</span>
            <span className="ml-2 text-muted-foreground">
              {s.computer}
            </span>
            {s.status && (
              <span className="ml-2 text-xs text-muted-foreground">
                ({s.status})
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
