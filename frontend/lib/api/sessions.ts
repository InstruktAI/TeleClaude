import type { SessionInfo } from "@/lib/api/types";

export async function fetchSessions(): Promise<SessionInfo[]> {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : data.sessions ?? [];
}
