"use client"

import { useEffect } from "react"
import { toast } from "sonner"
import { useWS } from "@/lib/ws/WebSocketProvider"
import type { WsEvent } from "@/lib/ws/types"

export function useSessionToasts() {
  const { onEvent } = useWS()

  useEffect(() => {
    const cleanupStarted = onEvent("session_started", (event: WsEvent) => {
      if (event.event !== "session_started") return
      const data = event.data as { session_id?: string; title?: string }
      const label = data.title ?? data.session_id ?? "Unknown"
      toast.success(`Session started: ${label}`)
    })

    const cleanupClosed = onEvent("session_closed", (event: WsEvent) => {
      if (event.event !== "session_closed") return
      const data = event.data as { session_id?: string }
      toast.info(`Session closed: ${data.session_id ?? "Unknown"}`)
    })

    return () => {
      cleanupStarted()
      cleanupClosed()
    }
  }, [onEvent])
}
