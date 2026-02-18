"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { Brain, Sparkles, Code2 } from "lucide-react";
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

function statusDot(status: string) {
  if (status === "active" || status === "running")
    return <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />;
  if (status === "idle")
    return <span className="h-2 w-2 rounded-full bg-yellow-500" />;
  return <span className="h-2 w-2 rounded-full bg-gray-400" />;
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

async function fetchSessions(): Promise<SessionInfo[]> {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : data.sessions ?? [];
}

export function SessionList() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeId = searchParams?.get("sessionId");

  const { data: sessions, isLoading, error } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    refetchInterval: 15_000,
  });

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 p-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3">
        <p className="text-xs text-destructive">
          Failed to load sessions
        </p>
      </div>
    );
  }

  const sorted = [...(sessions ?? [])].sort((a, b) => {
    const ta = a.last_activity ?? a.created_at ?? "";
    const tb = b.last_activity ?? b.created_at ?? "";
    return tb.localeCompare(ta);
  });

  if (sorted.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-sm text-muted-foreground">No active sessions</p>
        <p className="text-xs text-muted-foreground">
          Create one to get started
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1 p-2">
      {sorted.map((s) => {
        const isActive = s.session_id === activeId;
        const title = s.title || s.session_id.slice(0, 8);
        return (
          <button
            key={s.session_id}
            onClick={() => router.push(`/?sessionId=${s.session_id}`)}
            className={`flex items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${
              isActive
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "hover:bg-sidebar-accent/50"
            }`}
          >
            {agentIcon(s.active_agent)}
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-xs">{title}</p>
              {s.project_path && (
                <p className="truncate text-[10px] text-muted-foreground">
                  {s.project_path.split("/").pop()}
                </p>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground">
                {relativeTime(s.last_activity)}
              </span>
              {statusDot(s.status)}
            </div>
          </button>
        );
      })}
    </div>
  );
}
