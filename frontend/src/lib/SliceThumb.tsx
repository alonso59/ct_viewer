// Axial thumbnail (IMP-12): the API-26 WebP when the API serves one; the mock renders a mid-slice
// with the mask outline at the default W/L instead.
import { useEffect, useRef, useState } from 'react'

import { api, loadSlices, useConnection, type LabelDef } from '../api'
import { hexToRgb, renderSlice } from './slice'

const box = (size: number) =>
  ({
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
  }) as const

const Placeholder = () => <i className="codicon codicon-circle-slash" aria-hidden />

export function SliceThumb({ pid, itemId, labels, size = 40 }: { pid: string; itemId: string | null; labels?: LabelDef[]; size?: number }) {
  const url = itemId ? api.thumbnailUrl(pid, itemId) : null
  return (
    <span className="thumb" style={box(size)}>
      {!itemId ? <Placeholder /> : url ? <ServedThumb url={url} /> : <MockThumb itemId={itemId} labels={labels} />}
    </span>
  )
}

/** Thumbnails 404 until the background job made them; a finished thumbnail job retries (epoch) */
function ServedThumb({ url }: { url: string }) {
  const epoch = useConnection((s) => s.thumbEpoch)
  const [failed, setFailed] = useState<number | null>(null)
  if (failed === epoch) return <Placeholder />
  return (
    <img
      key={epoch}
      src={epoch ? `${url}?v=${epoch}` : url}
      alt=""
      loading="lazy"
      decoding="async"
      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
      onError={() => setFailed(epoch)}
    />
  )
}

function MockThumb({ itemId, labels }: { itemId: string; labels?: LabelDef[] }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [missing, setMissing] = useState(false)
  useEffect(() => {
    let live = true
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
  if (missing) return <Placeholder />
  return <canvas ref={ref} width={64} height={64} style={{ width: '100%', height: '100%', imageRendering: 'auto' }} />
}
