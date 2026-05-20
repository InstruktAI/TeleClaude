'use client';

import { useEffect, useCallback } from 'react';
import { findBinding } from '@/lib/keys/bindings';
import type { ViewContext } from '@/lib/keys/types';
import type { TabValue } from '@/components/TabBar';

const TAB_ACTIONS: Record<string, TabValue> = {
  switch_to_sessions: 'sessions',
  switch_to_preparation: 'preparation',
  switch_to_configuration: 'configuration',
  switch_to_jobs: 'jobs',
};

function isTextInput(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
  if ((el as HTMLElement).isContentEditable) return true;
  return false;
}

export interface UseKeyboardNavigationOptions {
  activeTab: TabValue;
  onSwitchTab: (tab: TabValue) => void;
  onEscape: () => void;
  onAction: (action: string) => void;
}

export function useKeyboardNavigation({ activeTab, onSwitchTab, onEscape, onAction }: UseKeyboardNavigationOptions) {
  const handler = useCallback(
    (e: KeyboardEvent) => {
      // Map browser key names to binding key names
      let bindingKey = e.key;
      const keyMap: Record<string, string> = {
        ArrowUp: 'upArrow',
        ArrowDown: 'downArrow',
        ArrowLeft: 'leftArrow',
        ArrowRight: 'rightArrow',
        Enter: 'return',
        Escape: 'escape',
        PageUp: 'pageUp',
        PageDown: 'pageDown',
      };
      if (keyMap[bindingKey]) bindingKey = keyMap[bindingKey];

      const modifiers = {
        ctrl: e.ctrlKey,
        shift: e.shiftKey,
        meta: e.metaKey,
      };

      // Escape always fires
      if (bindingKey === 'escape') {
        onEscape();
        return;
      }

      if (isTextInput(document.activeElement)) return;

      // Try global context first for tab switching
      const globalBinding = findBinding(bindingKey, modifiers, 'global');
      if (globalBinding && TAB_ACTIONS[globalBinding.action]) {
        onSwitchTab(TAB_ACTIONS[globalBinding.action]);
        return;
      }

      // Try active tab context
      const context = activeTab as ViewContext;
      const binding = findBinding(bindingKey, modifiers, context);
      if (binding && binding.context !== 'global') {
        onAction(binding.action);
        return;
      }

      // Global non-tab actions
      if (globalBinding) {
        onAction(globalBinding.action);
      }
    },
    [activeTab, onSwitchTab, onEscape, onAction],
  );

  useEffect(() => {
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [handler]);
}
