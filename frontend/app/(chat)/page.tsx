"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { LeftPanel } from "@/components/tui/LeftPanel";
import { SessionTree } from "@/components/tui/SessionTree";
import { Footer } from "@/components/tui/Footer";
import { ConfirmModal } from "@/components/tui/ConfirmModal";
import { NewSessionDialog } from "@/components/sidebar/NewSessionDialog";
import { SessionHeader } from "@/components/sidebar/SessionHeader";
import { ThemingToggle } from "@/components/parts/ThemingToggle";
import { DarkModeToggle } from "@/components/parts/DarkModeToggle";
import { TabBar } from "@/components/tabs/TabBar";
import { useActiveView } from "@/components/tabs/useActiveView";
import type { TabValue } from "@/components/tui/TabBar";
import type { SessionInfo } from "@/lib/api/types";
import type { ComputerGroup, NodeId } from "@/lib/sessions/tree";
import type { PanelId } from "@/lib/panels/navigation";
import { buildSessionTree, projectNodeId, sessionNodeId } from "@/lib/sessions/tree";
import { useSessions } from "@/lib/hooks/useSessions";
import { useComputers } from "@/lib/hooks/useComputers";
import { useEndSession, useAgentRestart } from "@/lib/hooks/useSessionActions";
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation";
import { useSessionTree } from "@/hooks/useSessionTree";
import { useSessionToasts } from "@/hooks/useSessionToasts";
import { useWS } from "@/lib/ws/WebSocketProvider";
import { findBinding } from "@/lib/keys/bindings";
import { toast } from "sonner";

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

type NewSessionPrefill = {
  computer?: string;
  project?: string;
};

function findProjectPrefill(
  tree: ComputerGroup[],
  nodeId: NodeId | null,
): NewSessionPrefill | undefined {
  if (!nodeId) return undefined;

  for (const computer of tree) {
    for (const project of computer.projects) {
      if (projectNodeId(computer.name, project.path) === nodeId) {
        return {
          computer: computer.name,
          project: project.path,
        };
      }
    }
  }

  return undefined;
}

function useSessionActivityMap() {
  const { onEvent } = useWS();
  const [activityMap, setActivityMap] = useState<Map<string, string>>(
    () => new Map(),
  );
  const timersRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const cleanup = onEvent("agent_activity", (event) => {
      if (event.event !== "agent_activity") return;

      setActivityMap((prev) => {
        const next = new Map(prev);
        next.set(event.session_id, event.type);
        return next;
      });

      const existing = timersRef.current.get(event.session_id);
      if (existing) window.clearTimeout(existing);

      const timer = window.setTimeout(() => {
        timersRef.current.delete(event.session_id);
        setActivityMap((prev) => {
          const next = new Map(prev);
          next.delete(event.session_id);
          return next;
        });
      }, 5_000);

      timersRef.current.set(event.session_id, timer);
    });

    return () => {
      cleanup();
      for (const timer of timersRef.current.values()) {
        window.clearTimeout(timer);
      }
      timersRef.current.clear();
    };
  }, [onEvent]);

  return activityMap;
}

const VIEW_ACTIONS: Record<string, PanelId> = {
  switch_to_sessions: "sessions",
  switch_to_preparation: "preparation",
  switch_to_configuration: "configuration",
  switch_to_jobs: "jobs",
};
function ChatPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams?.get("sessionId");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogPrefill, setDialogPrefill] = useState<NewSessionPrefill>();
  const [confirmEndOpen, setConfirmEndOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabValue>("sessions");
  const { refresh } = useWS();
  const { activeView, setActiveView } = useActiveView();
  const activityMap = useSessionActivityMap();
  const { data: sessions, isLoading: sessionsLoading, error: sessionsError } =
    useSessions();
  const {
    data: computers,
    isLoading: computersLoading,
    error: computersError,
  } = useComputers();
  const endSession = useEndSession();
  const restartAgent = useAgentRestart();

  useSessionToasts();

  const tree = useMemo(
    () => buildSessionTree(sessions ?? [], computers ?? []),
    [computers, sessions],
  );
  const {
    cursorId,
    expandedSet,
    setCursorId,
    moveCursor,
    toggleNode,
    expandAll,
    collapseAll,
    getNodeType,
    getSessionId,
  } = useSessionTree(tree);

  const selectedNodeType =
    activeTab === "sessions" && cursorId ? getNodeType(cursorId) : null;
  const selectedSessionId = cursorId ? getSessionId(cursorId) : null;
  const selectedSession = useMemo(
    () =>
      (sessions ?? []).find(
        (session: SessionInfo) => session.session_id === selectedSessionId,
      ) ?? null,
    [selectedSessionId, sessions],
  );

  useEffect(() => {
    if (!sessionId) return;
    setCursorId(sessionNodeId(sessionId));
  }, [sessionId, setCursorId]);

  const closeNewSessionDialog = useCallback((open: boolean) => {
    setDialogOpen(open);
    if (!open) setDialogPrefill(undefined);
  }, []);

  const openNewSessionDialog = useCallback((prefill?: NewSessionPrefill) => {
    setDialogPrefill(prefill);
    setDialogOpen(true);
  }, []);

  const handleSelectSession = useCallback(
    (nextSessionId: string) => {
      setCursorId(sessionNodeId(nextSessionId));
      router.push(`/?sessionId=${nextSessionId}`);
    },
    [router, setCursorId],
  );

  const handleEndSelectedSession = useCallback(async () => {
    if (!selectedSession) return;

    await endSession.mutateAsync({
      id: selectedSession.session_id,
      computer: selectedSession.computer ?? undefined,
    });
    setConfirmEndOpen(false);

    if (selectedSession.session_id === sessionId) {
      router.push("/");
    }
  }, [endSession, router, selectedSession, sessionId]);

  const handleRestartSelectedSession = useCallback(
    async (selectedId: string) => {
      await restartAgent.mutateAsync(selectedId);
      toast.success("Session restarted");
    },
    [restartAgent],
  );

  const handleEscape = useCallback(() => {
    if (confirmEndOpen) {
      setConfirmEndOpen(false);
      return;
    }

    if (dialogOpen) {
      closeNewSessionDialog(false);
      return;
    }

    setCursorId(null);
  }, [closeNewSessionDialog, confirmEndOpen, dialogOpen, setCursorId]);

  const handleAction = useCallback(
    (action: string) => {
      if (activeTab !== "sessions") {
        if (action === "refresh_data") refresh();
        return;
      }

      switch (action) {
        case "navigate_up":
          moveCursor("up");
          return;
        case "navigate_down":
          moveCursor("down");
          return;
        case "collapse_or_back":
          if (cursorId && expandedSet.has(cursorId)) {
            toggleNode(cursorId);
          }
          return;
        case "drill_down":
        case "toggle_project_sessions":
          if (cursorId) {
            toggleNode(cursorId);
          }
          return;
        case "expand_all":
          expandAll();
          return;
        case "collapse_all":
          collapseAll();
          return;
        case "activate_session": {
          if (!cursorId) return;

          const nextSessionId = getSessionId(cursorId);
          if (nextSessionId) {
            handleSelectSession(nextSessionId);
            return;
          }

          const prefill = findProjectPrefill(tree, cursorId);
          if (prefill) {
            openNewSessionDialog(prefill);
          }
          return;
        }
        case "new_session":
          openNewSessionDialog();
          return;
        case "kill_session":
          if (selectedSessionId) {
            setConfirmEndOpen(true);
          }
          return;
        case "restart_agent":
          if (selectedSessionId) {
            void handleRestartSelectedSession(selectedSessionId);
          }
          return;
        case "refresh_data":
          refresh();
          return;
      }
    },
    [
      activeTab,
      collapseAll,
      cursorId,
      expandAll,
      expandedSet,
      getSessionId,
      handleRestartSelectedSession,
      handleSelectSession,
      moveCursor,
      openNewSessionDialog,
      refresh,
      selectedSessionId,
      toggleNode,
      tree,
    ],
  );

  useKeyboardNavigation({
    activeTab,
    onSwitchTab: setActiveTab,
    onEscape: handleEscape,
    onAction: handleAction,
  });

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

  const sessionsContent = sessionsLoading || computersLoading ? (
    <div className="flex items-center justify-center p-6">
      <p className="text-sm text-muted-foreground">Loading sessions...</p>
    </div>
  ) : sessionsError || computersError ? (
    <div className="flex items-center justify-center p-6">
      <p className="text-sm text-destructive">Failed to load sessions</p>
    </div>
  ) : (
    <SessionTree
      tree={tree}
      expandedSet={expandedSet}
      cursorId={cursorId}
      activeSessionId={sessionId}
      activityMap={activityMap}
      onToggle={toggleNode}
      onSelectSession={handleSelectSession}
      onCursorChange={setCursorId}
    />
  );

  return (
    <>
      {/* Left panel — 40% */}
      <LeftPanel
        activeTab={activeTab}
        onTabChange={setActiveTab}
        sessionsContent={sessionsContent}
        footer={
          <Footer
            context={activeTab}
            selectedNodeType={
              activeTab === "sessions"
                ? selectedNodeType ?? (sessionId ? "session" : null)
                : null
            }
          />
        }
      />

      {/* Right panel — 60% */}
      <main className="flex min-w-0 flex-col" style={{ width: "60%" }}>
        <header className="flex items-center gap-2 border-b px-4 py-2">
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

      <NewSessionDialog
        open={dialogOpen}
        onOpenChange={closeNewSessionDialog}
        prefill={dialogPrefill}
      />
      <ConfirmModal
        open={confirmEndOpen}
        onOpenChange={setConfirmEndOpen}
        title="End session?"
        message="This will stop the selected session."
        onConfirm={() => {
          void handleEndSelectedSession();
        }}
      />
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
