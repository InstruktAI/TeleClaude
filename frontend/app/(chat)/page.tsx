"use client";

import { Suspense, useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { Menu } from "lucide-react";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { useSidebar } from "@/components/sidebar/SidebarProvider";
import { NewSessionDialog } from "@/components/sidebar/NewSessionDialog";
import { SessionHeader } from "@/components/sidebar/SessionHeader";
import { ThemingToggle } from "@/components/parts/ThemingToggle";
import { DarkModeToggle } from "@/components/parts/DarkModeToggle";
import { TabBar } from "@/components/tabs/TabBar";
import { useActiveView } from "@/components/tabs/useActiveView";
import type { PanelId } from "@/lib/panels/navigation";
import { findBinding } from "@/lib/keys/bindings";

const Chat = dynamic(() => import("@/components/assistant/Chat"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-1 items-center justify-center">
      <p className="text-sm text-muted-foreground">Loading...</p>
    </div>
  ),
});

const PreparationView = dynamic(
  () =>
    import("@/components/preparation/PreparationView").then(
      (m) => m.PreparationView,
    ),
  { ssr: false },
);

const ConfigView = dynamic(
  () =>
    import("@/components/configuration/ConfigView").then((m) => m.ConfigView),
  { ssr: false },
);

const JobsView = dynamic(
  () => import("@/components/jobs/JobsView").then((m) => m.JobsView),
  { ssr: false },
);

const VIEW_ACTIONS: Record<string, PanelId> = {
  switch_to_sessions: "sessions",
  switch_to_preparation: "preparation",
  switch_to_configuration: "configuration",
  switch_to_jobs: "jobs",
};

function ChatPageInner() {
  const searchParams = useSearchParams();
  const sessionId = searchParams?.get("sessionId");
  const { toggle } = useSidebar();
  const [dialogOpen, setDialogOpen] = useState(false);
  const { activeView, setActiveView } = useActiveView();

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Skip when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      const binding = findBinding(
        e.key,
        { ctrl: e.ctrlKey, shift: e.shiftKey, meta: e.metaKey },
        activeView,
      );

      if (binding && binding.action in VIEW_ACTIONS) {
        e.preventDefault();
        setActiveView(VIEW_ACTIONS[binding.action]);
      }
    },
    [activeView, setActiveView],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

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
          {sessionId && activeView === "sessions" ? (
            <SessionHeader sessionId={sessionId} />
          ) : (
            <h1 className="text-lg font-semibold">TeleClaude</h1>
          )}
          <div className="ml-auto flex items-center gap-1">
            <DarkModeToggle />
            <ThemingToggle />
          </div>
        </header>

        <TabBar activeView={activeView} onViewChange={setActiveView} />

        {/* Views — all rendered simultaneously, hidden via display:none to preserve state (R1.2) */}
        <div className="flex-1 overflow-hidden relative">
          <div
            className="absolute inset-0 overflow-hidden"
            style={{ display: activeView === "sessions" ? "block" : "none" }}
          >
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
          <div
            className="absolute inset-0 overflow-auto"
            style={{
              display: activeView === "preparation" ? "block" : "none",
            }}
          >
            <PreparationView isActive={activeView === "preparation"} />
          </div>
          <div
            className="absolute inset-0 overflow-auto"
            style={{
              display: activeView === "configuration" ? "block" : "none",
            }}
          >
            <ConfigView isActive={activeView === "configuration"} />
          </div>
          <div
            className="absolute inset-0 overflow-auto"
            style={{ display: activeView === "jobs" ? "block" : "none" }}
          >
            <JobsView isActive={activeView === "jobs"} />
          </div>
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
