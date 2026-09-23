// Axial thumbnail with mask outline at the default W/L (IMP-12 look). P2 swaps in API-26 WebP.
import { useEffect, useRef, useState } from 'react'

import { loadSlices, type LabelDef } from '../api'
import { hexToRgb, renderSlice } from './slice'

export function SliceThumb({ itemId, labels, size = 40 }: { itemId: string | null; labels?: LabelDef[]; size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [missing, setMissing] = useState(false)
  useEffect(() => {
    let live = true
    if (!itemId) return
    void loadSlices().then((all) => {
      const s = all.get(itemId)
      const ctx = ref.current?.getContext('2d')
      if (!live || !ctx) return
      if (!s) {
        setMissing(true)
        return
      }
      const lab = new Map<number, [number, number, number, number]>()
      for (const l of labels ?? []) lab.set(l.value, [...hexToRgb(l.color), 1])
      renderSlice(ctx, {
        w: s.image.axial.w,
        h: s.image.axial.h,
        image: s.image.axial.data,
        mask: s.mask?.axial.data,
        ww: 400,
        wl: 50,
        labels: lab,
        outline: true,
      })
    })
    return () => {
      live = false
    }
  }, [itemId, labels])
  return (
    <span
      className="thumb"
      style={{
        width: size,
        height: size,
        flex: 'none',
        borderRadius: 4,
        overflow: 'hidden',
        background: 'var(--bg-viewport)',
        border: '1px solid var(--border)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--fg-viewport-muted)',
      }}
    >
      {itemId && !missing ? (
        <canvas ref={ref} width={64} height={64} style={{ width: '100%', height: '100%', imageRendering: 'auto' }} />
      ) : (
        <i className="codicon codicon-circle-slash" aria-hidden />
      )}
    </span>
  )
}
