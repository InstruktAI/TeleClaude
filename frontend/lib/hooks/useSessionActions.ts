"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { SessionInfo } from "@/lib/api/types";

export function useEndSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      computer,
    }: {
      id: string;
      computer?: string;
    }) => {
      const qs = computer ? `?computer=${encodeURIComponent(computer)}` : "";
      const res = await fetch(`/api/sessions/${encodeURIComponent(id)}${qs}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `Failed to end session: ${res.status}`);
      }
      return res.json();
    },
    onMutate: async ({ id }) => {
      await queryClient.cancelQueries({ queryKey: ["sessions"] });
      const previous = queryClient.getQueryData<SessionInfo[]>(["sessions"]);
      if (previous) {
        queryClient.setQueryData(
          ["sessions"],
          previous.filter((s) => s.session_id !== id),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["sessions"], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useCreateSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      computer: string;
      title?: string;
      initial_message?: string;
    }) => {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(
          errBody.error ?? `Failed to create session: ${res.status}`,
        );
      }
      return res.json();
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useAgentRestart() {
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(
        `/api/sessions/${encodeURIComponent(id)}/agent-restart`,
        { method: "POST" },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          body.error ?? `Failed to restart agent: ${res.status}`,
        );
      }
      return res.json();
    },
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (patch: Record<string, unknown>) => {
      const res = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          body.error ?? `Failed to update settings: ${res.status}`,
        );
      }
      return res.json();
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}
