"use client";

import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { ComputerCard } from "@/components/dashboard/ComputerCard";
import type { ComputerInfo, SessionInfo, ProjectInfo } from "@/lib/api/types";

async function fetchComputers(): Promise<ComputerInfo[]> {
  const res = await fetch("/api/computers");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchSessions(): Promise<SessionInfo[]> {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : data.sessions ?? [];
}

async function fetchProjectsForComputer(
  computer: string,
): Promise<ProjectInfo[]> {
  const res = await fetch(
    `/api/projects?computer=${encodeURIComponent(computer)}`,
  );
  if (!res.ok) return [];
  return res.json();
}

export default function DashboardPage() {
  const {
    data: computers,
    isLoading: computersLoading,
    error: computersError,
  } = useQuery({
    queryKey: ["computers"],
    queryFn: fetchComputers,
    refetchInterval: 30_000,
  });

  const { data: sessions, isLoading: sessionsLoading } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    refetchInterval: 15_000,
  });

  const { data: projectsByComputer } = useQuery({
    queryKey: ["dashboard-projects", computers?.map((c) => c.name)],
    queryFn: async () => {
      if (!computers) return {};
      const results: Record<string, ProjectInfo[]> = {};
      await Promise.all(
        computers.map(async (c) => {
          results[c.name] = await fetchProjectsForComputer(c.name);
        }),
      );
      return results;
    },
    enabled: !!computers && computers.length > 0,
  });

  const isLoading = computersLoading || sessionsLoading;
  const totalSessions = sessions?.length ?? 0;

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 border-b px-6 py-3">
        <Link
          href="/"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <LayoutDashboard className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-lg font-semibold">Admin Dashboard</h1>
        <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          <span>
            {computers?.length ?? 0} computer
            {(computers?.length ?? 0) !== 1 ? "s" : ""}
          </span>
          <span className="text-muted-foreground/50">·</span>
          <span>
            {totalSessions} active session
            {totalSessions !== 1 ? "s" : ""}
          </span>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-y-auto p-6">
        {isLoading && (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-40 animate-pulse rounded-xl border bg-muted"
              />
            ))}
          </div>
        )}

        {computersError && (
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-center">
            <p className="text-sm text-destructive">
              Failed to load computers
            </p>
          </div>
        )}

        {!isLoading && computers && (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {computers.map((c) => (
              <ComputerCard
                key={c.name}
                computer={c}
                sessions={sessions ?? []}
                projects={(projectsByComputer?.[c.name] ?? []).map((p) => ({
                  name: p.name,
                  path: p.path,
                }))}
              />
            ))}
          </div>
        )}

        {!isLoading && computers?.length === 0 && (
          <div className="flex items-center justify-center py-16">
            <p className="text-sm text-muted-foreground">
              No computers configured
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
