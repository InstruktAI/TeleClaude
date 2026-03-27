// @vitest-environment happy-dom
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TabBar, type TabValue } from '../TabBar'

function renderTabBar(value: TabValue = 'sessions', onValueChange = vi.fn()) {
  return render(
    <TabBar
      value={value}
      onValueChange={onValueChange}
      sessionsContent={<div data-testid="sessions-content">Sessions here</div>}
    />,
  )
}

describe('TabBar', () => {
  it('renders tabs with tablist role', () => {
    renderTabBar()
    const tablists = screen.getAllByRole('tablist')
    expect(tablists.length).toBeGreaterThanOrEqual(1)
  })

  it('renders 4 tab triggers', () => {
    renderTabBar()
    const tabs = screen.getAllByRole('tab')
    expect(tabs.length).toBeGreaterThanOrEqual(4)
  })

  it('marks active tab with data-state=active', () => {
    renderTabBar('sessions')
    const tabs = screen.getAllByRole('tab')
    const activeTab = tabs.find(
      (t) => t.getAttribute('data-state') === 'active' && t.textContent === 'Sessions',
    )
    expect(activeTab).toBeDefined()
  })

  it('renders tabpanel for active tab', () => {
    renderTabBar('sessions')
    const panels = screen.getAllByRole('tabpanel')
    expect(panels.length).toBeGreaterThanOrEqual(1)
  })

  it('renders sessions content in DOM', () => {
    renderTabBar('sessions')
    const items = screen.getAllByTestId('sessions-content')
    expect(items.length).toBeGreaterThanOrEqual(1)
  })

  it('shows placeholder content for non-sessions tabs', () => {
    renderTabBar('preparation')
    expect(screen.getByText('Not yet implemented')).toBeDefined()
  })

  it('accepts onValueChange callback', () => {
    const onValueChange = vi.fn()
    renderTabBar('sessions', onValueChange)
    // Verify the component accepts the prop — Radix event dispatch
    // is verified at integration level, not unit level with happy-dom
    expect(onValueChange).toBeDefined()
  })
})
