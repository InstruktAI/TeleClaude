import { describe, it, expect } from "vitest"
import { findBinding, getFooterHints, BINDINGS } from "../bindings"
import type { ViewContext } from "../types"

describe("bindings — jobs tab", () => {
  it("findBinding resolves key 4 to switch_to_jobs in global context", () => {
    const binding = findBinding("4", {}, "global")
    expect(binding).toBeDefined()
    expect(binding!.action).toBe("switch_to_jobs")
  })

  it("jobs is a valid ViewContext accepted by findBinding", () => {
    const ctx: ViewContext = "jobs"
    const binding = findBinding("escape", {}, ctx)
    expect(binding).toBeDefined()
    expect(binding!.action).toBe("go_back")
  })
})

describe("bindings — k conflict resolution", () => {
  it("k in sessions context resolves to kill_session (not navigate_up)", () => {
    const binding = findBinding("k", {}, "sessions")
    expect(binding).toBeDefined()
    expect(binding!.action).toBe("kill_session")
  })

  it("k is not bound to navigate_up in sessions context", () => {
    const sessionsBindings = BINDINGS.filter(
      (b) => b.key === "k" && b.context === "sessions",
    )
    const navUp = sessionsBindings.find((b) => b.action === "navigate_up")
    expect(navUp).toBeUndefined()
  })
})

describe("bindings — footer hints", () => {
  it("getFooterHints exposes the binding action for selection-aware filtering", () => {
    const hints = getFooterHints("sessions")
    expect(hints.length).toBeGreaterThan(0)
    expect(hints[0]).toHaveProperty("action")
  })
})
