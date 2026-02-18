"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Brain, Sparkles, Code2, Square } from "lucide-react";
import { useState } from "react";
import type { SessionInfo } from "@/lib/api/types";

function agentIcon(agent: string | null | undefined) {
  switch (agent) {
    case "gemini":
      return <Sparkles className="h-3.5 w-3.5 text-blue-500" />;
    case "codex":
      return <Code2 className="h-3.5 w-3.5 text-green-500" />;
    default:
      return <Brain className="h-3.5 w-3.5 text-purple-500" />;
  }
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    active: "bg-green-500/10 text-green-700",
    running: "bg-green-500/10 text-green-700",
    idle: "bg-yellow-500/10 text-yellow-700",
    stopped: "bg-gray-500/10 text-gray-600",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${colors[status] ?? colors.stopped}`}
    >
      {status}
    </span>
  );
}

async function fetchSessions(): Promise<SessionInfo[]> {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : data.sessions ?? [];
}

interface Props {
  sessionId: string;
}

export function SessionHeader({ sessionId }: Props) {
  const router = useRouter();
  const [ending, setEnding] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);

  const { data: sessions } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
  });

  const session = sessions?.find((s) => s.session_id === sessionId);

  async function handleEndSession() {
    if (!session) return;
    setEnding(true);
    try {
      const computer = session.computer ?? "local";
      const res = await fetch(
        `/api/sessions/${sessionId}?computer=${encodeURIComponent(computer)}`,
        { method: "DELETE" },
      );
      if (res.ok) {
        router.push("/");
      }
    } finally {
      setEnding(false);
      setConfirmEnd(false);
    }
  }

  if (!session) {
    return <span className="text-sm text-muted-foreground">Loading...</span>;
  }

  const title = session.title || sessionId.slice(0, 8);

  return (
    <div className="flex flex-1 items-center gap-2">
      {agentIcon(session.active_agent)}
      <span className="truncate text-sm font-medium">{title}</span>
      {session.computer && (
        <span className="text-[10px] text-muted-foreground">
          {session.computer}
        </span>
      )}
      {statusBadge(session.status)}
      <div className="ml-auto flex items-center gap-1">
        {confirmEnd ? (
          <div className="flex items-center gap-1">
            <span className="text-xs text-muted-foreground">End session?</span>
            <button
              onClick={handleEndSession}
              disabled={ending}
              className="rounded px-2 py-1 text-xs font-medium text-destructive hover:bg-destructive/10"
            >
              {ending ? "Ending..." : "Yes"}
            </button>
            <button
              onClick={() => setConfirmEnd(false)}
              className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent"
            >
              No
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmEnd(true)}
            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            aria-label="End session"
          >
            <Square className="h-3 w-3" />
            End
          </button>
        )}
      </div>
    </div>
  );
}
