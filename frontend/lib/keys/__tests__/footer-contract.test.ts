import { describe, expect, it } from "vitest"
import { getFooterRows } from "../footer-contract"

describe("footer contract", () => {
  it("limits sessions footer to the mirrored subset for a selected session", () => {
    const { contextHints, globalHints } = getFooterRows("sessions", "session")
    const text = [...contextHints, ...globalHints]
      .map((hint) => `${hint.key} ${hint.description}`)
      .join(" | ")

    expect(text).toContain("Space Preview")
    expect(text).toContain("Enter Focus")
    expect(text).toContain("+ All")
    expect(text).toContain("- None")
    expect(text).toContain("k Kill session")
    expect(text).toContain("R Restart")

    expect(text).not.toContain("Navigate up")
    expect(text).not.toContain("Navigate down")
    expect(text).not.toContain("PgUp")
    expect(text).not.toContain("PgDn")
    expect(text).not.toContain("Refresh")
    expect(text).not.toContain("Colors")
  })

  it("keeps project node hints focused on project-level actions", () => {
    const { contextHints } = getFooterRows("sessions", "project")
    const text = contextHints.map((hint) => `${hint.key} ${hint.description}`).join(" | ")

    expect(text).toContain("Enter New session")
    expect(text).toContain("n New session")
    expect(text).toContain("+ All")
    expect(text).toContain("- None")
    expect(text).not.toContain("Kill session")
    expect(text).not.toContain("Restart")
    expect(text).not.toContain("Preview")
  })

  it("hides session-only hints on computer nodes", () => {
    const { contextHints } = getFooterRows("sessions", "computer")
    const text = contextHints.map((hint) => `${hint.key} ${hint.description}`).join(" | ")

    expect(text).toContain("+ All")
    expect(text).toContain("- None")
    expect(text).not.toContain("Enter")
    expect(text).not.toContain("New session")
    expect(text).not.toContain("Kill session")
  })

  it("keeps configuration footer to the TUI-like visible subset", () => {
    const { contextHints } = getFooterRows("configuration")
    const text = contextHints.map((hint) => `${hint.key} ${hint.description}`).join(" | ")

    expect(text).toContain("Enter Select/Toggle")
    expect(text).toContain("Tab Next tab")
    expect(text).toContain("Shift+Tab Previous tab")
    expect(text).not.toContain("Navigate up")
    expect(text).not.toContain("Navigate down")
    expect(text).not.toContain("Previous subtab")
    expect(text).not.toContain("Next subtab")
  })
})
