import { describe, it, expect } from "vitest";
import { displayTitle, headlessPrefix } from "@/lib/sessions/displayTitle";

describe("headlessPrefix", () => {
  it("returns [HEADLESS] marker for headless sessions", () => {
    expect(headlessPrefix({ status: "headless" })).toBe("[HEADLESS] ");
  });

  it("returns empty string for non-headless sessions", () => {
    expect(headlessPrefix({ status: "active" })).toBe("");
  });

  it("returns empty string when status is missing", () => {
    expect(headlessPrefix({})).toBe("");
  });
});

describe("displayTitle", () => {
  it("prepends the headless marker to the title for headless sessions", () => {
    expect(displayTitle({ status: "headless", title: "My session" })).toBe(
      "[HEADLESS] My session",
    );
  });

  it("returns the bare title for non-headless sessions", () => {
    expect(displayTitle({ status: "active", title: "My session" })).toBe("My session");
  });

  it("uses the explicit fallback string when title is missing", () => {
    expect(displayTitle({ status: "active" }, "Custom fallback")).toBe("Custom fallback");
  });

  it("defaults the fallback to 'Untitled' when none is provided", () => {
    expect(displayTitle({})).toBe("Untitled");
  });

  it("applies the headless marker even when title falls back", () => {
    expect(displayTitle({ status: "headless" })).toBe("[HEADLESS] Untitled");
  });
});
