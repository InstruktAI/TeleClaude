"use client";

import { useEffect, useState } from "react";
import type { AgentAvailabilityEvent, AgentAvailabilityInfo, AgentName } from "@/lib/api/types";
import { useAgentAvailability } from "@/lib/hooks/useAgentAvailability";
import { useWS } from "@/lib/ws/WebSocketProvider";

export function useLiveAgentAvailability() {
  const query = useAgentAvailability();
  const { onEvent } = useWS();
  const [availability, setAvailability] = useState<Record<string, AgentAvailabilityInfo>>(
    () => query.data ?? {},
  );

  useEffect(() => {
    if (query.data) {
      setAvailability(query.data);
      return;
    }
    if (!query.isLoading) {
      setAvailability({});
    }
  }, [query.data, query.isLoading]);

  useEffect(() => {
    return onEvent("agent_availability", (event) => {
      if (event.event !== "agent_availability") return;
      const availabilityEvent = event as AgentAvailabilityEvent;
      const agent = availabilityEvent.data.agent as AgentName;
      setAvailability((prev) => ({
        ...prev,
        [agent]: availabilityEvent.data,
      }));
    });
  }, [onEvent]);

  return {
    data: availability,
    isLoading: query.isLoading && query.data === undefined,
    error: query.error,
    refetch: query.refetch,
  };
}
