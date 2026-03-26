"use client";

import { useQuery } from "@tanstack/react-query";
import type { JobInfo } from "@/lib/api/types";

async function fetchJobs(): Promise<JobInfo[]> {
  const res = await fetch("/api/jobs");
  if (!res.ok) throw new Error(`Failed to fetch jobs: ${res.status}`);
  return res.json();
}

export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: fetchJobs,
  });
}
