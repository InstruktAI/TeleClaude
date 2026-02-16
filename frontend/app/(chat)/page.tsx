"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { SessionPicker } from "@/components/SessionPicker";

const Chat = dynamic(() => import("@/components/assistant/Chat"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-1 items-center justify-center">
      <p className="text-sm text-muted-foreground">Loading...</p>
    </div>
  ),
});

function ChatPageInner() {
  const searchParams = useSearchParams();
  const sessionId = searchParams?.get("sessionId");

  if (!sessionId) {
    return <SessionPicker />;
  }

  return <Chat key={sessionId} sessionId={sessionId} />;
}

export default function ChatPage() {
  return (
    <>
      <header className="border-b px-4 py-2">
        <h1 className="text-lg font-semibold">TeleClaude</h1>
      </header>
      <main className="flex-1 overflow-hidden">
        <Suspense
          fallback={
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-muted-foreground">Loading...</p>
            </div>
          }
        >
          <ChatPageInner />
        </Suspense>
      </main>
    </>
  );
}
