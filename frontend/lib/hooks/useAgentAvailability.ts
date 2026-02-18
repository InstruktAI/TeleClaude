"use client";

import { useQuery } from "@tanstack/react-query";
import type { AgentAvailabilityInfo } from "@/lib/api/types";

async function fetchAgentAvailability(): Promise<
  Record<string, AgentAvailabilityInfo>
> {
  const res = await fetch("/api/agents/availability");
  if (!res.ok)
    throw new Error(`Failed to fetch agent availability: ${res.status}`);
  return res.json();
}

export function useAgentAvailability() {
  return useQuery({
    queryKey: ["agents", "availability"],
    queryFn: fetchAgentAvailability,
  });
}
