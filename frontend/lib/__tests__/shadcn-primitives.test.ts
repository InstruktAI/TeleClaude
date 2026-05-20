/**
 * Module-resolution smoke test for shadcn/ui primitives.
 *
 * Verifies that each installed primitive is importable and exports
 * the expected component functions.
 */

import { describe, it, expect } from 'vitest';

describe('shadcn/ui primitives', () => {
  it('exports Tabs components', async () => {
    const mod = await import('@/components/ui/tabs');
    expect(mod.Tabs).toBeDefined();
    expect(mod.TabsList).toBeDefined();
    expect(mod.TabsTrigger).toBeDefined();
    expect(mod.TabsContent).toBeDefined();
  });

  it('exports Dialog components', async () => {
    const mod = await import('@/components/ui/dialog');
    expect(mod.Dialog).toBeDefined();
    expect(mod.DialogContent).toBeDefined();
    expect(mod.DialogHeader).toBeDefined();
    expect(mod.DialogTitle).toBeDefined();
  });

  it('exports ScrollArea component', async () => {
    const mod = await import('@/components/ui/scroll-area');
    expect(mod.ScrollArea).toBeDefined();
  });

  it('exports Badge component', async () => {
    const mod = await import('@/components/ui/badge');
    expect(mod.Badge).toBeDefined();
  });

  it('exports Tooltip components', async () => {
    const mod = await import('@/components/ui/tooltip');
    expect(mod.Tooltip).toBeDefined();
    expect(mod.TooltipTrigger).toBeDefined();
    expect(mod.TooltipContent).toBeDefined();
    expect(mod.TooltipProvider).toBeDefined();
  });

  it('exports Toaster from sonner', async () => {
    const mod = await import('@/components/ui/sonner');
    expect(mod.Toaster).toBeDefined();
  });
});
