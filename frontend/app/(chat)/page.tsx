"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import dynamic from "next/dynamic";
import { LeftPanel } from "@/components/LeftPanel";
import { SessionTree } from "@/components/SessionTree";
import { Footer } from "@/components/Footer";
import { ConfirmModal } from "@/components/ConfirmModal";
import { NewSessionDialog } from "@/components/sidebar/NewSessionDialog";
import { SessionHeader } from "@/components/sidebar/SessionHeader";
import { ThemingToggle } from "@/components/parts/ThemingToggle";
import { DarkModeToggle } from "@/components/parts/DarkModeToggle";
import type { TabValue } from "@/components/TabBar";
import type { SessionInfo } from "@/lib/api/types";
import type { ComputerGroup, NodeId } from "@/lib/sessions/tree";
import { buildSessionTree, projectNodeId, sessionNodeId } from "@/lib/sessions/tree";
import { useComputers } from "@/lib/hooks/useComputers";
import { useEndSession, useAgentRestart } from "@/lib/hooks/useSessionActions";
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation";
import { useLiveSessions } from "@/hooks/useLiveSessions";
import { usePersistentState } from "@/hooks/usePersistentState";
import { useSessionHighlights } from "@/hooks/useSessionHighlights";
import { useSessionTree } from "@/hooks/useSessionTree";
import { useSessionToasts } from "@/hooks/useSessionToasts";
import { useWS } from "@/lib/ws/WebSocketProvider";
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

const CHAT_LAYOUT_STORAGE_KEY = "teleclaude.chat.layout";

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

function ChatPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: authSession } = useSession();
  const sessionId = searchParams?.get("sessionId");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogPrefill, setDialogPrefill] = useState<NewSessionPrefill>();
  const [confirmEndOpen, setConfirmEndOpen] = useState(false);
  const { refresh } = useWS();
  const [layoutState, setLayoutState] = usePersistentState<{
    activeTab: TabValue;
    lastSessionId: string | null;
  }>(CHAT_LAYOUT_STORAGE_KEY, {
    activeTab: "sessions",
    lastSessionId: null,
  });
  const activeTab = layoutState.activeTab;
  const lastSessionId = layoutState.lastSessionId ?? null;
  const restoredSessionIdRef = useRef<string | null>(null);
  const {
    data: sessions,
    isLoading: sessionsLoading,
    error: sessionsError,
    refetch: refetchSessions,
  } = useLiveSessions();
  const {
    data: computers,
    isLoading: computersLoading,
    error: computersError,
  } = useComputers();
  const endSession = useEndSession();
  const restartAgent = useAgentRestart();

  useSessionToasts();

  const sessionHighlights = useSessionHighlights(sessions, sessionId);

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
    expandScope,
    collapseScope,
    revealSession,
    getNodeType,
    getSessionId,
  } = useSessionTree(tree, {
    isReady: !sessionsLoading && !computersLoading,
  });

  const selectedNodeType =
    activeTab === "sessions" && cursorId ? getNodeType(cursorId) : null;
  const selectedSessionId = cursorId ? getSessionId(cursorId) : null;
  const currentUserEmail =
    typeof authSession?.user?.email === "string" ? authSession.user.email : null;
  const selectedSession = useMemo(
    () =>
      (sessions ?? []).find(
        (session: SessionInfo) => session.session_id === selectedSessionId,
      ) ?? null,
    [selectedSessionId, sessions],
  );

  useEffect(() => {
    if (!sessionId) return;

    restoredSessionIdRef.current = null;
    revealSession(sessionId);
    setLayoutState((prev) =>
      prev.lastSessionId === sessionId
        ? prev
        : { ...prev, lastSessionId: sessionId },
    );
  }, [revealSession, sessionId, setLayoutState]);

  useEffect(() => {
    if (sessionId) return;
    if (!lastSessionId) return;
    if (!sessions?.some((session) => session.session_id === lastSessionId)) {
      setLayoutState((prev) =>
        prev.lastSessionId === null ? prev : { ...prev, lastSessionId: null },
      );
      return;
    }
    if (restoredSessionIdRef.current === lastSessionId) return;

    restoredSessionIdRef.current = lastSessionId;
    router.push(`/?sessionId=${lastSessionId}`);
  }, [lastSessionId, router, sessionId, sessions, setLayoutState]);

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
      revealSession(nextSessionId);
      setLayoutState((prev) => ({
        ...prev,
        lastSessionId: nextSessionId,
      }));
      router.push(`/?sessionId=${nextSessionId}`);
    },
    [revealSession, router, setLayoutState],
  );

  const handleTabChange = useCallback(
    (tab: TabValue) => {
      setLayoutState((prev) => ({ ...prev, activeTab: tab }));
    },
    [setLayoutState],
  );

  const handleEndSelectedSession = useCallback(async () => {
    if (!selectedSession) return;

    await endSession.mutateAsync({
      id: selectedSession.session_id,
      computer: selectedSession.computer ?? undefined,
    });
    setConfirmEndOpen(false);

    if (selectedSession.session_id === sessionId) {
      setLayoutState((prev) => ({ ...prev, lastSessionId: null }));
      router.push("/");
    }
  }, [endSession, router, selectedSession, sessionId, setLayoutState]);

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
        if (action === "refresh_data") {
          refresh();
          void refetchSessions();
        }
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
          expandScope(cursorId);
          return;
        case "collapse_all":
          collapseScope(cursorId);
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
          void refetchSessions();
          return;
      }
    },
    [
      activeTab,
      collapseScope,
      cursorId,
      expandScope,
      expandedSet,
      getSessionId,
      handleRestartSelectedSession,
      handleSelectSession,
      moveCursor,
      openNewSessionDialog,
      refetchSessions,
      refresh,
      selectedSessionId,
      toggleNode,
      tree,
    ],
  );

  useKeyboardNavigation({
    activeTab,
    onSwitchTab: handleTabChange,
    onEscape: handleEscape,
    onAction: handleAction,
  });

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
      sessionStateMap={sessionHighlights}
      currentUserEmail={currentUserEmail}
      onToggle={toggleNode}
      onSelectSession={handleSelectSession}
      onCursorChange={setCursorId}
    />
  );

  const preparationContent = (
    <PreparationView isActive={activeTab === "preparation"} />
  );
  const configurationContent = (
    <ConfigView isActive={activeTab === "configuration"} />
  );
  const jobsContent = <JobsView isActive={activeTab === "jobs"} />;

  return (
    <>
      <LeftPanel
        activeTab={activeTab}
        onTabChange={handleTabChange}
        sessionsContent={sessionsContent}
        preparationContent={preparationContent}
        configurationContent={configurationContent}
        jobsContent={jobsContent}
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

      <main className="flex min-w-0 flex-col" style={{ width: "60%" }}>
        <header className="flex items-center gap-2 border-b px-4 py-2">
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

        <div className="flex-1 overflow-hidden">
          {sessionId ? (
            <Chat key={sessionId} sessionId={sessionId} />
          ) : (
            <div className="flex h-full flex-1 items-center justify-center">
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
