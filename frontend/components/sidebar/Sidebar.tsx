"use client";

import { Suspense } from "react";
import { Plus } from "lucide-react";
import { SessionList } from "./SessionList";
import { useSidebar } from "./SidebarProvider";
import { useWS } from "@/lib/ws/WebSocketProvider";

function ConnectionBadge() {
  const { status } = useWS();
  if (status === "connected") return null;
  const label =
    status === "connecting"
      ? "Connecting..."
      : status === "reconnecting"
        ? "Reconnecting..."
        : "Disconnected";
  return (
    <span className="rounded-full bg-yellow-500/10 px-2 py-0.5 text-[10px] text-yellow-600">
      {label}
    </span>
  );
}

interface SidebarProps {
  onNewSession: () => void;
}

export function Sidebar({ onNewSession }: SidebarProps) {
  const { open, close } = useSidebar();

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={close}
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r bg-sidebar text-sidebar-foreground
          transition-transform duration-200
          md:static md:z-0 md:translate-x-0
          ${open ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Sessions</h2>
          <div className="flex items-center gap-2">
            <ConnectionBadge />
            <button
              onClick={onNewSession}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-sidebar-accent"
              aria-label="New session"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto">
          <Suspense
            fallback={
              <div className="flex flex-col gap-2 p-3">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="h-14 animate-pulse rounded-lg bg-muted"
                  />
                ))}
              </div>
            }
          >
            <SessionList />
          </Suspense>
        </div>
      </aside>
    </>
  );
}
