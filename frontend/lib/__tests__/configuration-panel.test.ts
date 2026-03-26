/**
 * Test specifications for the configuration panel.
 *
 * Behavioral contract: the configuration surface is admin-gated, exposes the
 * five required subtabs, keeps most sections read-only because the daemon lacks
 * write endpoints, masks environment values by default, and supports keyboard
 * subtab/item navigation.
 *
 * All tests are marked as expected failures (it.fails) until implementation exists.
 */

import { describe, expect, it } from "vitest";

describe("resolveConfigurationAccess", () => {
  it("allows admins and denies non-admins", async () => {
    const modulePath = "@/lib/configuration/panel" as string;
    const { resolveConfigurationAccess } = await import(modulePath);

    expect(resolveConfigurationAccess("admin")).toEqual({
      canOpen: true,
      presentation: "full",
    });
    const memberAccess = resolveConfigurationAccess("member");
    expect(memberAccess.canOpen).toBe(false);
    expect(["hidden", "disabled", "denied"]).toContain(memberAccess.presentation);
  });
});

describe("getConfigurationSubtabs", () => {
  it("returns the five required subtabs in keyboard order", async () => {
    const modulePath = "@/lib/configuration/panel" as string;
    const { getConfigurationSubtabs } = await import(modulePath);

    expect(
      getConfigurationSubtabs().map((tab: { id: string }) => tab.id),
    ).toEqual([
      "adapters",
      "people",
      "notifications",
      "environment",
      "validate",
    ]);
  });

  it("marks read-only subtabs according to daemon endpoint availability", async () => {
    const modulePath = "@/lib/configuration/panel" as string;
    const { getConfigurationSubtabs } = await import(modulePath);

    expect(
      getConfigurationSubtabs().map(
        (tab: { id: string; readOnly: boolean; actionState: string }) => ({
          id: tab.id,
          readOnly: tab.readOnly,
          actionState: tab.actionState,
        }),
      ),
    ).toEqual([
      { id: "adapters", readOnly: true, actionState: "read_only" },
      { id: "people", readOnly: true, actionState: "read_only" },
      { id: "notifications", readOnly: true, actionState: "read_only" },
      { id: "environment", readOnly: true, actionState: "read_only" },
      { id: "validate", readOnly: true, actionState: "cli_only_placeholder" },
    ]);
  });
});

describe("buildEnvironmentEntries", () => {
  it("masks values by default and reveals only the selected key", async () => {
    const modulePath = "@/lib/configuration/panel" as string;
    const { buildEnvironmentEntries } = await import(modulePath);

    const entries = buildEnvironmentEntries(
      {
        OPENAI_API_KEY: "sk-live-secret",
        TELECLAUDE_ENV: "local-dev",
      },
      { revealedKeys: ["TELECLAUDE_ENV"] },
    );

    expect(entries).toHaveLength(2);
    expect(entries[0]).toEqual(
      expect.objectContaining({
        key: "OPENAI_API_KEY",
        masked: true,
      }),
    );
    expect(entries[0].value).not.toBe("sk-live-secret");
    expect(entries[1]).toEqual({
      key: "TELECLAUDE_ENV",
      masked: false,
      value: "local-dev",
    });
  });
});
