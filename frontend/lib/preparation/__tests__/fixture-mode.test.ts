import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadPreparationFixture } from "@/lib/preparation/fixture-mode";

describe("loadPreparationFixture security guard", () => {
  beforeEach(() => {
    vi.stubEnv("NODE_ENV", "test");
    vi.stubEnv("NEXT_PUBLIC_E2E_FIXTURES", "1");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns daemon-backed null when NODE_ENV is production regardless of fixture name", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(loadPreparationFixture("smoke")).toBeNull();
  });

  it("returns null when an unknown fixture name is requested", () => {
    expect(loadPreparationFixture("__not_in_allowlist__")).toBeNull();
  });

  it("returns the fixture set when NODE_ENV is non-production and the fixture name is allowlisted", () => {
    const result = loadPreparationFixture("smoke");
    expect(result).not.toBeNull();
    expect(result!.projects.length).toBeGreaterThan(0);
    expect(result!.computers.length).toBeGreaterThan(0);
  });
});
