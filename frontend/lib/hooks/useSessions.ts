"use client";

import { useQuery } from "@tanstack/react-query";
import type { SessionInfo } from "@/lib/api/types";

async function fetchSessions(computer?: string): Promise<SessionInfo[]> {
  const qs = computer ? `?computer=${encodeURIComponent(computer)}` : "";
  const res = await fetch(`/api/sessions${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch sessions: ${res.status}`);
  return res.json();
}

export function useSessions(computer?: string) {
  return useQuery({
    queryKey: ["sessions", computer ?? "all"],
    queryFn: () => fetchSessions(computer),
  });
}
