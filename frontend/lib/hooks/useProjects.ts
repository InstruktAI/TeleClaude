"use client";

import { useQuery } from "@tanstack/react-query";
import type { ProjectInfo } from "@/lib/api/types";

async function fetchProjects(computer?: string): Promise<ProjectInfo[]> {
  const qs = computer ? `?computer=${encodeURIComponent(computer)}` : "";
  const res = await fetch(`/api/projects${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch projects: ${res.status}`);
  return res.json();
}

export function useProjects(computer?: string) {
  return useQuery({
    queryKey: ["projects", computer ?? "all"],
    queryFn: () => fetchProjects(computer),
  });
}
