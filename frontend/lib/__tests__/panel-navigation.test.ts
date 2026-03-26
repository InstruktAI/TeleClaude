/**
 * Test specifications for web TUI panel navigation.
 *
 * Behavioral contract: the chat surface exposes four persistent panels
 * (sessions, preparation, configuration, jobs), supports the documented
 * global shortcuts, and preserves each panel's local state when the user
 * switches away and back.
 *
 * All tests are marked as expected failures (it.fails) until implementation exists.
 */

import { describe, expect, it } from "vitest";
import { findBinding } from "@/lib/keys/bindings";

describe("panel navigation bindings", () => {
  it("registers global shortcut 4 for the jobs panel", () => {
    const binding = findBinding("4", {}, "sessions");

    expect(binding).toMatchObject({
      key: "4",
      context: "global",
      action: "switch_to_jobs",
      description: "Jobs tab",
    });
  });

  it("normalizes browser key names to Ink-style names", () => {
    const arrowUp = findBinding("ArrowUp", {}, "sessions");
    expect(arrowUp).toMatchObject({ action: "navigate_up", context: "sessions" });

    const enter = findBinding("Enter", {}, "sessions");
    expect(enter).toMatchObject({ action: "activate_session", context: "sessions" });

    const escape = findBinding("Escape", {}, "global");
    expect(escape).toMatchObject({ action: "go_back", context: "global" });

    const tab = findBinding("Tab", {}, "configuration");
    expect(tab).toMatchObject({ action: "next_tab", context: "configuration" });
  });
});

