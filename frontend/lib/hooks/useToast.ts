'use client';

import { useSyncExternalStore, useCallback } from 'react';
import type { ToastVariant } from '@/components/ui/toast';

export interface ToastData {
  id: string;
  title: string;
  description?: string;
  variant?: ToastVariant;
}

let toastCounter = 0;
let toasts: ToastData[] = [];
const listeners = new Set<() => void>();

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): ToastData[] {
  return toasts;
}

function getServerSnapshot(): ToastData[] {
  return [];
}

export function toast(data: Omit<ToastData, 'id'>): string {
  toastCounter += 1;
  const id = `toast-${toastCounter}`;
  toasts = [...toasts, { ...data, id }];
  emitChange();
  return id;
}

export function dismissToast(id: string): void {
  toasts = toasts.filter((t) => t.id !== id);
  emitChange();
}

export function useToast() {
  const currentToasts = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const dismiss = useCallback((id: string) => {
    dismissToast(id);
  }, []);

  return { toasts: currentToasts, toast, dismiss };
}
