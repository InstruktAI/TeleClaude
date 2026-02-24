"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Brain, Sparkles, Code2, Square } from "lucide-react";
import { useState } from "react";
import { fetchSessions } from "@/lib/api/sessions";
import type { SessionInfo } from "@/lib/api/types";
import { useAgentColors } from "@/hooks/useAgentColors";
import { safeAgent } from "@/lib/theme/tokens";

function AgentIcon({
  agent,
  color,
}: {
  agent: string | null | undefined;
  color: string;
}) {
  const props = { className: "h-3.5 w-3.5", style: { color } };
  switch (agent) {
    case "gemini":
      return <Sparkles {...props} />;
    case "codex":
      return <Code2 {...props} />;
    default:
      return <Brain {...props} />;
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

interface Props {
  sessionId: string;
}

export function SessionHeader({ sessionId }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [ending, setEnding] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [endError, setEndError] = useState<string | null>(null);

  const { data: sessions } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
  });

  const session = sessions?.find((s) => s.session_id === sessionId);
  const agentColors = useAgentColors(safeAgent(session?.active_agent || "codex"));

  async function handleEndSession() {
    if (!session) return;
    setEnding(true);
    setEndError(null);
    try {
      const computer = session.computer ?? "local";
      const res = await fetch(
        `/api/sessions/${sessionId}?computer=${encodeURIComponent(computer)}`,
        { method: "DELETE" },
      );
      if (res.ok) {
        await queryClient.invalidateQueries({ queryKey: ["sessions"] });
        router.push("/");
      } else {
        const data = await res.json().catch(() => ({}));
        setEndError(data.error ?? `Failed to end session (HTTP ${res.status})`);
      }
    } catch {
      setEndError("Failed to end session");
    } finally {
      setEnding(false);
      setConfirmEnd(false);
    }
  }

  if (!session) {
    return <span className="text-sm text-muted-foreground">Loading...</span>;
  }

  const projectName = session.project_path?.split("/").filter(Boolean).pop() || "TeleClaude";
  const title = session.title || "Untitled";

  return (
    <div className="flex flex-1 items-center gap-2 overflow-hidden">
      <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/60">
        {projectName}
      </span>
      <span className="shrink-0 text-muted-foreground/30">/</span>
      <span className="shrink-0 font-mono text-[10px] text-muted-foreground/80">
        {session.session_id}
      </span>
      <span className="shrink-0 text-muted-foreground/30">/</span>

      <div className="flex shrink-0 items-center ml-1">
        <AgentIcon agent={session.active_agent} color={agentColors.sidebarText} />
      </div>

      <span className="truncate text-sm font-semibold">{title}</span>

      {session.computer && (
        <span className="ml-1 shrink-0 text-[10px] text-muted-foreground">
          @{session.computer}
        </span>
      )}
      <div className="shrink-0 ml-1">
        {statusBadge(session.status)}
      </div>

      <div className="ml-auto flex items-center gap-1">
        {endError && (
          <span className="text-xs text-destructive">{endError}</span>
        )}
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
              onClick={() => {
                setConfirmEnd(false);
                setEndError(null);
              }}
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
