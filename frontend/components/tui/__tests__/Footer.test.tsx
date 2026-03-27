// @vitest-environment happy-dom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { Footer } from '../Footer'

describe('Footer', () => {
  afterEach(() => cleanup())

  it('renders kbd elements for session context hints', () => {
    const { container } = render(<Footer context="sessions" />)
    const kbds = container.querySelectorAll('kbd')
    expect(kbds.length).toBeGreaterThan(0)
  })

  it('shows navigation hints (arrows, n) for sessions context', () => {
    const { container } = render(<Footer context="sessions" />)
    const text = container.textContent ?? ''
    expect(text).toContain('↑')
    expect(text).toContain('↓')
    expect(text).toContain('New session')
  })

  it('shows session-specific hints (Enter, R, k) when a session is selected', () => {
    const { container } = render(
      <Footer context="sessions" selectedNodeType="session" />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('Enter')
    expect(text).toContain('Kill session')
  })

  it('changes hint set when context switches to preparation', () => {
    const { container } = render(<Footer context="preparation" />)
    const text = container.textContent ?? ''
    expect(text).toContain('↑')
    expect(text).toContain('↓')
    // Preparation has its own bindings like "Start work"
    expect(text).toContain('Start work')
  })

  it('each hint contains a kbd element and a description span', () => {
    const { container } = render(<Footer context="sessions" />)
    const hints = container.querySelectorAll('[data-testid="footer-hint"]')
    expect(hints.length).toBeGreaterThan(0)
    for (const hint of hints) {
      expect(hint.querySelector('kbd')).not.toBeNull()
      expect(hint.querySelector('span')).not.toBeNull()
    }
  })

  it('shows global quit binding', () => {
    const { container } = render(<Footer context="sessions" />)
    const text = container.textContent ?? ''
    expect(text).toContain('Quit')
  })
})
