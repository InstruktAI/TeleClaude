"use client"

import { useMemo } from "react"
import { getFooterHints } from "@/lib/keys/bindings"
import type { ViewContext } from "@/lib/keys/types"

interface FooterProps {
  context: ViewContext
  selectedNodeType?: "computer" | "project" | "session" | null
}

const SESSION_ONLY_ACTIONS = new Set([
  "kill_session",
  "restart_agent",
  "space_action",
])

export function Footer({ context, selectedNodeType }: FooterProps) {
  const hints = useMemo(() => {
    const base = getFooterHints(context)

    if (context !== "sessions") {
      return base
    }

    return base.flatMap((hint) => {
      if (hint.action === "activate_session") {
        if (selectedNodeType === "session") {
          return [hint]
        }
        if (selectedNodeType === "project") {
          return [{ ...hint, description: "New session" }]
        }
        return []
      }

      if (selectedNodeType !== "session" && SESSION_ONLY_ACTIONS.has(hint.action)) {
        return []
      }

      return [hint]
    })
  }, [context, selectedNodeType])

  return (
    <div className="flex flex-wrap gap-2 border-t px-3 py-2 text-[10px]">
      {hints.map((hint, i) => (
        <div key={`${hint.key}-${i}`} data-testid="footer-hint" className="flex items-center gap-1">
          <kbd className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
            {hint.key}
          </kbd>
          <span className="text-muted-foreground">{hint.description}</span>
        </div>
      ))}
    </div>
  )
}
