"use client";

import { useQuery } from "@tanstack/react-query";
import type { TodoInfo } from "@/lib/api/types";

async function fetchTodos(): Promise<TodoInfo[]> {
  const res = await fetch("/api/todos");
  if (!res.ok) throw new Error(`Failed to fetch todos: ${res.status}`);
  return res.json();
}

export function useTodos() {
  return useQuery({
    queryKey: ["todos"],
    queryFn: fetchTodos,
  });
}
