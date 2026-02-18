"use client";

import { Monitor, Wifi, WifiOff } from "lucide-react";
import type { ComputerInfo, SessionInfo } from "@/lib/api/types";
import { ProjectRow } from "./ProjectRow";

interface Props {
  computer: ComputerInfo;
  sessions: SessionInfo[];
  projects: { name: string; path: string }[];
}

export function ComputerCard({ computer, sessions, projects }: Props) {
  const isOnline = computer.status === "online" || computer.status === "active";
  const sessionCount = sessions.filter(
    (s) => s.computer === computer.name,
  ).length;

  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
          <Monitor className="h-5 w-5 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-semibold">{computer.name}</h3>
            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              {computer.is_local ? "local" : "remote"}
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {isOnline ? (
              <Wifi className="h-3 w-3 text-green-500" />
            ) : (
              <WifiOff className="h-3 w-3 text-gray-400" />
            )}
            <span>{isOnline ? "Online" : "Offline"}</span>
            <span className="text-muted-foreground/50">·</span>
            <span>
              {sessionCount} session{sessionCount !== 1 ? "s" : ""}
            </span>
          </div>
        </div>
      </div>

      {projects.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <div className="flex flex-col gap-1">
            {projects.map((p) => {
              const projSessions = sessions.filter(
                (s) =>
                  s.computer === computer.name && s.project_path === p.path,
              ).length;
              return (
                <ProjectRow
                  key={p.path}
                  name={p.name}
                  path={p.path}
                  sessionCount={projSessions}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
