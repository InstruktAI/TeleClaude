"use client";

import type { PanelId } from "@/lib/panels/navigation";
import { cn } from "@/lib/utils";

const TABS: { id: PanelId; label: string; shortcut: string }[] = [
  { id: "sessions", label: "Sessions", shortcut: "1" },
  { id: "preparation", label: "Preparation", shortcut: "2" },
  { id: "configuration", label: "Configuration", shortcut: "3" },
  { id: "jobs", label: "Jobs", shortcut: "4" },
];

interface TabBarProps {
  activeView: PanelId;
  onViewChange: (view: PanelId) => void;
}

export function TabBar({ activeView, onViewChange }: TabBarProps) {
  return (
    <div className="flex border-b px-4" role="tablist">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={activeView === tab.id}
          onClick={() => onViewChange(tab.id)}
          className={cn(
            "relative flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors",
            activeView === tab.id
              ? "text-foreground"
              : "text-muted-foreground hover:text-foreground/80",
          )}
        >
          {tab.label}
          <span className="text-[10px] text-muted-foreground/60">
            {tab.shortcut}
          </span>
          {activeView === tab.id && (
            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />
          )}
        </button>
      ))}
    </div>
  );
}
