"use client";

import dynamic from "next/dynamic";

const Chat = dynamic(() => import("@/components/assistant/Chat"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-1 items-center justify-center">
      <p className="text-sm text-muted-foreground">Loading...</p>
    </div>
  ),
});

export default function ChatPage() {
  return (
    <>
      <header className="border-b px-4 py-2">
        <h1 className="text-lg font-semibold">TeleClaude</h1>
      </header>
      <main className="flex-1 overflow-hidden">
        <Chat />
      </main>
    </>
  );
}
