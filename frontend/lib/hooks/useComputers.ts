"use client";

import { useQuery } from "@tanstack/react-query";
import type { ComputerInfo } from "@/lib/api/types";

async function fetchComputers(): Promise<ComputerInfo[]> {
  const res = await fetch("/api/computers");
  if (!res.ok) throw new Error(`Failed to fetch computers: ${res.status}`);
  return res.json();
}

export function useComputers() {
  return useQuery({
    queryKey: ["computers"],
    queryFn: fetchComputers,
  });
}
