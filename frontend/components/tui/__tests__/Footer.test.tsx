// @vitest-environment happy-dom
import { describe, it, expect, afterEach } from "vitest"
import { render, cleanup } from "@testing-library/react"
import { Footer } from "../Footer"

describe("Footer", () => {
  afterEach(() => cleanup())

  it("renders kbd elements for session context hints", () => {
    const { container } = render(<Footer context="sessions" />)
    const kbds = container.querySelectorAll("kbd")
    expect(kbds.length).toBeGreaterThan(0)
  })

  it("shows the mirrored sessions hints instead of the raw binding map", () => {
    const { container } = render(<Footer context="sessions" />)
    const text = container.textContent ?? ""
    expect(text).toContain("New session")
    expect(text).toContain("All")
    expect(text).toContain("None")
    expect(text).not.toContain("Navigate up")
    expect(text).not.toContain("Navigate down")
    expect(text).not.toContain("Drill down")
  })

  it("shows session-specific hints (Enter, R, k) when a session is selected", () => {
    const { container } = render(
      <Footer context="sessions" selectedNodeType="session" />,
    )
    const text = container.textContent ?? ""
    expect(text).toContain("Enter")
    expect(text).toContain("Kill session")
    expect(text).toContain("Restart")
  })

  it("changes hint set when context switches to preparation", () => {
    const { container } = render(<Footer context="preparation" />)
    const text = container.textContent ?? ""
    expect(text).toContain("Preview file")
    expect(text).toContain("Start work")
    expect(text).not.toContain("Navigate up")
    expect(text).not.toContain("Navigate down")
  })

  it("each hint contains a kbd element and a description span", () => {
    const { container } = render(<Footer context="sessions" />)
    const hints = container.querySelectorAll('[data-testid="footer-hint"]')
    expect(hints.length).toBeGreaterThan(0)
    for (const hint of hints) {
      expect(hint.querySelector('kbd')).not.toBeNull()
      expect(hint.querySelector('span')).not.toBeNull()
    }
  })

  it("shows only the curated global row hints", () => {
    const { container } = render(<Footer context="sessions" />)
    const text = container.textContent ?? ""
    expect(text).toContain("Quit")
    expect(text).toContain("TTS")
    expect(text).toContain("Back")
    expect(text).not.toContain("Sessions tab")
  })
})
