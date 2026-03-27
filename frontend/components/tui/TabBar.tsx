"use client"

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import type { ReactNode } from "react"

export type TabValue = "sessions" | "preparation" | "configuration" | "monitoring"

interface TabBarProps {
  value: TabValue
  onValueChange: (value: TabValue) => void
  sessionsContent: ReactNode
}

const TABS: Array<{ value: TabValue; label: string }> = [
  { value: "sessions", label: "Sessions" },
  { value: "preparation", label: "Preparation" },
  { value: "configuration", label: "Configuration" },
  { value: "monitoring", label: "Monitoring" },
]

export function TabBar({ value, onValueChange, sessionsContent }: TabBarProps) {
  return (
    <Tabs
      value={value}
      onValueChange={(v) => onValueChange(v as TabValue)}
      className="flex flex-1 flex-col min-h-0"
    >
      <TabsList className="w-full justify-start rounded-none border-b bg-transparent p-0">
        {TABS.map((tab) => (
          <TabsTrigger
            key={tab.value}
            value={tab.value}
            className="rounded-none border-b-2 border-transparent px-3 py-2 text-xs data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none"
          >
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>

      <TabsContent value="sessions" className="flex-1 min-h-0 mt-0">
        {sessionsContent}
      </TabsContent>
      <TabsContent value="preparation" className="flex-1 min-h-0 mt-0 p-4">
        <p className="text-sm text-muted-foreground">Not yet implemented</p>
      </TabsContent>
      <TabsContent value="configuration" className="flex-1 min-h-0 mt-0 p-4">
        <p className="text-sm text-muted-foreground">Not yet implemented</p>
      </TabsContent>
      <TabsContent value="monitoring" className="flex-1 min-h-0 mt-0 p-4">
        <p className="text-sm text-muted-foreground">Not yet implemented</p>
      </TabsContent>
    </Tabs>
  )
}
