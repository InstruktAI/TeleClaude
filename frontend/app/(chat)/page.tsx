"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { Menu } from "lucide-react";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useSidebar } from "@/components/sidebar/SidebarProvider";
import { NewSessionDialog } from "@/components/sidebar/NewSessionDialog";
import { SessionHeader } from "@/components/sidebar/SessionHeader";
import { ThemingToggle } from "@/components/parts/ThemingToggle";
import { DarkModeToggle } from "@/components/parts/DarkModeToggle";

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
  const { toggle } = useSidebar();
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      <Sidebar onNewSession={() => setDialogOpen(true)} />
      <main className="flex min-w-0 flex-1 flex-col">
        {/* Top bar with hamburger for mobile */}
        <header className="flex items-center gap-2 border-b px-4 py-2">
          <button
            onClick={toggle}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-accent md:hidden"
            aria-label="Toggle sidebar"
          >
            <Menu className="h-4 w-4" />
          </button>
          {sessionId ? (
            <SessionHeader sessionId={sessionId} />
          ) : (
            <h1 className="text-lg font-semibold">TeleClaude</h1>
          )}
          <div className="ml-auto flex items-center gap-1">
            <DarkModeToggle />
            <ThemingToggle />
          </div>
        </header>

        {/* Chat area */}
        <div className="flex-1 overflow-hidden">
          {sessionId ? (
            <Chat key={sessionId} sessionId={sessionId} />
          ) : (
            <div className="flex flex-1 items-center justify-center h-full">
              <div className="text-center">
                <p className="text-sm text-muted-foreground">
                  Select a session from the sidebar
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  or create a new one
                </p>
              </div>
            </div>
          )}
        </div>
      </main>
      <NewSessionDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      }
    >
      <ChatPageInner />
    </Suspense>
  );
}
