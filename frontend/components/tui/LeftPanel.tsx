"use client"

import { useState, type ReactNode } from "react"
import { TabBar, type TabValue } from "./TabBar"

interface LeftPanelProps {
  sessionsContent: ReactNode
  footer: ReactNode
  activeTab?: TabValue
  onTabChange?: (tab: TabValue) => void
}

export function LeftPanel({
  sessionsContent,
  footer,
  activeTab,
  onTabChange,
}: LeftPanelProps) {
  const [internalTab, setInternalTab] = useState<TabValue>("sessions")
  const tab = activeTab ?? internalTab
  const setTab = onTabChange ?? setInternalTab

  return (
    <div
      className="flex flex-col border-r bg-sidebar text-sidebar-foreground"
      style={{ width: "40%" }}
    >
      <TabBar
        value={tab}
        onValueChange={setTab}
        sessionsContent={sessionsContent}
      />
      <div className="border-t px-2 py-1.5">{footer}</div>
    </div>
  )
}
