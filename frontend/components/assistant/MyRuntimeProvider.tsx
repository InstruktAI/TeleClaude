"use client";

import { type ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";

const chatModelAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: messages.map((m) => ({
          role: m.role,
          content:
            m.content
              ?.filter((p) => p.type === "text")
              .map((p) => p.text)
              .join("\n") ?? "",
        })),
      }),
      signal: abortSignal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Request failed" }));
      throw new Error(err.error ?? `HTTP ${res.status}`);
    }

    const data = await res.json();
    yield {
      content: [{ type: "text" as const, text: data.message ?? data.text ?? JSON.stringify(data) }],
    };
  },
};

export function MyRuntimeProvider({ children }: { children: ReactNode }) {
  const runtime = useLocalRuntime(chatModelAdapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
