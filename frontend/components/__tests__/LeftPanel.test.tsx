// @vitest-environment happy-dom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { LeftPanel } from '../LeftPanel'

describe('LeftPanel', () => {
  afterEach(() => cleanup())

  function renderLeftPanel(activeTab?: "sessions" | "preparation" | "configuration" | "jobs") {
    return render(
      <LeftPanel
        activeTab={activeTab}
        sessionsContent={<div>sessions</div>}
        preparationContent={<div>preparation</div>}
        configurationContent={<div>configuration</div>}
        jobsContent={<div>jobs</div>}
        footer={<div>footer</div>}
      />,
    )
  }

  it('renders with 40% width', () => {
    const { container } = renderLeftPanel()
    const panel = container.firstElementChild as HTMLElement
    expect(panel.style.width).toBe('40%')
  })

  it('contains a tab bar with tablist role', () => {
    renderLeftPanel()
    const tablists = screen.getAllByRole('tablist')
    expect(tablists.length).toBeGreaterThanOrEqual(1)
  })

  it('renders footer slot', () => {
    render(
      <LeftPanel
        sessionsContent={<div>sessions</div>}
        preparationContent={<div>preparation</div>}
        configurationContent={<div>configuration</div>}
        jobsContent={<div>jobs</div>}
        footer={<div data-testid="test-footer">footer content</div>}
      />,
    )
    expect(screen.getByTestId('test-footer')).toBeDefined()
  })

  it('renders active tab based on activeTab prop', () => {
    renderLeftPanel('preparation')
    const tabs = screen.getAllByRole('tab')
    const activePrepTab = tabs.find(
      (t) => t.textContent?.includes('Preparation') && t.getAttribute('data-state') === 'active',
    )
    expect(activePrepTab).toBeDefined()
  })
})
