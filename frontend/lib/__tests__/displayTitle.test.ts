import { describe, it, expect } from "vitest";
import { displayTitle, headlessPrefix } from "@/lib/sessions/displayTitle";

describe("headlessPrefix", () => {
  it("returns [HEADLESS] marker for headless sessions", () => {
    expect(headlessPrefix({ lifecycle_status: "headless" })).toBe("[HEADLESS] ");
  });

  it("returns empty string for non-headless sessions", () => {
    expect(headlessPrefix({ lifecycle_status: "active" })).toBe("");
  });

  it("returns empty string when lifecycle_status is missing", () => {
    expect(headlessPrefix({})).toBe("");
  });
});

describe("displayTitle", () => {
  it("prepends the headless marker to the title for headless sessions", () => {
    expect(displayTitle({ lifecycle_status: "headless", title: "My session" })).toBe(
      "[HEADLESS] My session",
    );
  });

  it("returns the bare title for non-headless sessions", () => {
    expect(displayTitle({ lifecycle_status: "active", title: "My session" })).toBe("My session");
  });

  it("falls back to the explicit fallback string when title is missing", () => {
    expect(displayTitle({ lifecycle_status: "active" }, "Untitled")).toBe("Untitled");
  });

  it("falls back to a short session id when title and fallback are missing", () => {
    expect(displayTitle({ lifecycle_status: "active", session_id: "abc12345-rest" })).toBe(
      "abc12345",
    );
  });

  it("falls back to literal 'Untitled' when nothing identifying is provided", () => {
    expect(displayTitle({})).toBe("Untitled");
  });

  it("applies the headless marker even when title falls back", () => {
    expect(displayTitle({ lifecycle_status: "headless", session_id: "abc12345-rest" })).toBe(
      "[HEADLESS] abc12345",
    );
  });
});
