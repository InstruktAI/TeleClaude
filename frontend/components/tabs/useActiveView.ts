"use client";

import { useState, useCallback } from "react";
import type { PanelId } from "@/lib/panels/navigation";

export function useActiveView(defaultView: PanelId = "sessions") {
  const [activeView, setActiveViewState] = useState<PanelId>(defaultView);

  const setActiveView = useCallback((view: PanelId) => {
    setActiveViewState(view);
  }, []);

  return { activeView, setActiveView };
}
