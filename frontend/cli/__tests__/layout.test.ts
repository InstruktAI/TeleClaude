import { describe, it, expect } from 'vitest'
import { getLayoutSignature, LAYOUT_SPECS } from '../lib/tmux/layout.js'

describe('getLayoutSignature', () => {
  it('should return empty string when no panes', () => {
    const sig = getLayoutSignature([], null)
    // 1 TUI pane, LAYOUT_SPECS[1] exists
    expect(sig).not.toBe('')
    expect(JSON.parse(sig)).toEqual([1, 1, [['T']], []])
  })

  it('should include sticky IDs in structural keys', () => {
    const sig = getLayoutSignature(['a'], null)
    const parsed = JSON.parse(sig)
    expect(parsed[3]).toContain('a')
    expect(parsed[3]).not.toContain('__active__')
  })

  it('should include __active__ when preview is not sticky', () => {
    const sig = getLayoutSignature(['a'], 'b')
    const parsed = JSON.parse(sig)
    expect(parsed[3]).toContain('a')
    expect(parsed[3]).toContain('__active__')
  })

  it('should NOT count previewId as extra slot when it is already in stickyIds', () => {
    // This is the core fix: preview of a sticky session must not inflate the slot count
    const sigStickyOnly = getLayoutSignature(['a'], null)
    const sigStickyWithSamePreview = getLayoutSignature(['a'], 'a')
    expect(sigStickyWithSamePreview).toBe(sigStickyOnly)
  })

  it('should produce different signatures for different structural configurations', () => {
    const sigNoPreview = getLayoutSignature(['a'], null)
    const sigWithPreview = getLayoutSignature(['a'], 'b')
    expect(sigNoPreview).not.toBe(sigWithPreview)
  })

  it('should be stable for same inputs', () => {
    expect(getLayoutSignature(['a', 'b'], null)).toBe(getLayoutSignature(['a', 'b'], null))
  })

  it('should produce different signatures for different sticky ID lists', () => {
    const sig1 = getLayoutSignature(['a'], null)
    const sig2 = getLayoutSignature(['b'], null)
    expect(sig1).not.toBe(sig2)
  })

  it('should match slot count to pane spec for 2 stickies with preview of one', () => {
    // stickyIds=[A,B], previewId=A → effective preview is null → 2 slots → LAYOUT_SPECS[3]
    const sig = getLayoutSignature(['A', 'B'], 'A')
    const parsed = JSON.parse(sig)
    const spec = LAYOUT_SPECS[3]
    expect(parsed[0]).toBe(spec.rows)
    expect(parsed[1]).toBe(spec.cols)
  })
})
