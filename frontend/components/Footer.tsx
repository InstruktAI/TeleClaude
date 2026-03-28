"use client"

import { useMemo } from "react"
import { getFooterRows } from "@/lib/keys/footer-contract"
import type { FooterContext } from "@/lib/keys/footer-contract"

export interface FooterProps {
  context: FooterContext
  selectedNodeType?: "computer" | "project" | "session" | null
}

export function Footer({ context, selectedNodeType }: FooterProps) {
  const { contextHints, globalHints } = useMemo(() => {
    return getFooterRows(context, selectedNodeType)
  }, [context, selectedNodeType])

  return (
    <div className="flex flex-col gap-1 px-1 text-[10px]">
      <div data-testid="footer-context-row" className="flex flex-wrap gap-2">
        {contextHints.map((hint, index) => (
          <div
            key={`${hint.action}-${index}`}
            data-testid="footer-hint"
            className="flex items-center gap-1"
          >
            <kbd className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
              {hint.key}
            </kbd>
            <span className="text-muted-foreground">{hint.description}</span>
          </div>
        ))}
      </div>
      <div data-testid="footer-global-row" className="flex flex-wrap gap-2">
        {globalHints.map((hint, index) => (
          <div
            key={`${hint.action}-${index}`}
            data-testid="footer-hint"
            className="flex items-center gap-1"
          >
            <kbd className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">
              {hint.key}
            </kbd>
            <span className="text-muted-foreground">{hint.description}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
