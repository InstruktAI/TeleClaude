// @vitest-environment happy-dom
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LeftPanel } from '../LeftPanel'

describe('LeftPanel', () => {
  it('renders with 40% width', () => {
    const { container } = render(
      <LeftPanel
        sessionsContent={<div>sessions</div>}
        footer={<div>footer</div>}
      />,
    )
    const panel = container.firstElementChild as HTMLElement
    expect(panel.style.width).toBe('40%')
  })

  it('contains a tab bar with tablist role', () => {
    render(
      <LeftPanel
        sessionsContent={<div>sessions</div>}
        footer={<div>footer</div>}
      />,
    )
    const tablists = screen.getAllByRole('tablist')
    expect(tablists.length).toBeGreaterThanOrEqual(1)
  })

  it('renders footer slot', () => {
    render(
      <LeftPanel
        sessionsContent={<div>sessions</div>}
        footer={<div data-testid="test-footer">footer content</div>}
      />,
    )
    expect(screen.getByTestId('test-footer')).toBeDefined()
  })

  it('renders active tab based on activeTab prop', () => {
    render(
      <LeftPanel
        activeTab="preparation"
        sessionsContent={<div>sessions</div>}
        footer={<div>footer</div>}
      />,
    )
    const tabs = screen.getAllByRole('tab')
    const activePrepTab = tabs.find(
      (t) => t.textContent === 'Preparation' && t.getAttribute('data-state') === 'active',
    )
    expect(activePrepTab).toBeDefined()
  })
})
