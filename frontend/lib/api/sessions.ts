import type { SessionInfo } from "@/lib/api/types";

export async function fetchSessions(): Promise<SessionInfo[]> {
  // console.log("fetchSessions called");
  const res = await fetch("/api/sessions");
  if (!res.ok) {
    console.error(`fetchSessions failed: HTTP ${res.status}`);
    throw new Error(`HTTP ${res.status}`);
  }
  const text = await res.text();
  try {
    const data = JSON.parse(text);
    return Array.isArray(data) ? data : data.sessions ?? [];
  } catch (err) {
    console.error("Failed to parse sessions JSON:", text);
    throw err;
  }
}
