"use client";

import { useState, useCallback } from "react";
import { useComposerRuntime } from "@assistant-ui/react";
import type { ActionsSection as ActionsSectionType } from "@/lib/widgets";

export function ActionsSectionRenderer({ section }: { section: ActionsSectionType }) {
  const composer = useComposerRuntime();
  const [clickedAction, setClickedAction] = useState<string | null>(null);

  const handleClick = useCallback(
    (action: string, confirm?: string) => {
      if (confirm && !window.confirm(confirm)) return;
      const message = `Action: ${action}`;
      composer.setText(message);
      composer.send();
      setClickedAction(action);
    },
    [composer],
  );

  const isVertical = section.layout === "vertical";

  return (
    <div className={`flex gap-2 ${isVertical ? "flex-col" : "flex-row flex-wrap"}`}>
      {section.buttons.map((btn) => {
        const isClicked = clickedAction === btn.action;
        const styleClass =
          btn.style === "destructive"
            ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
            : btn.style === "secondary"
              ? "border bg-background hover:bg-accent"
              : "bg-primary text-primary-foreground hover:bg-primary/90";

        return (
          <button
            key={btn.action}
            onClick={() => handleClick(btn.action, btn.confirm)}
            disabled={btn.disabled || isClicked}
            className={`inline-flex items-center rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${styleClass}`}
          >
            {btn.label}
          </button>
        );
      })}
    </div>
  );
}
