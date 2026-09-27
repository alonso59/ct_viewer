// Axial thumbnail (IMP-12): the API-26 WebP when the API serves one; the mock renders a mid-slice
// with the mask outline at the default W/L instead.
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, loadSlices, useConnection, type LabelDef } from '../api'
import { CtIcon } from '../theme'
import { hexToRgb, renderSlice } from './slice'

/** A missing thumbnail (not built yet, no image or not decodable): a muted CT-set placeholder on
 *  the inset colour with a tooltip; real slices stay on the black viewport colour (AUD-A3-11/12) */
function Placeholder() {
  const { t } = useTranslation()
  return (
    <span className="thumb-empty" title={t('explorer.noThumbnail')}>
      <CtIcon name="slice-stack" />
    </span>
  )
}

export function SliceThumb({ pid, itemId, labels, size = 40 }: { pid: string; itemId: string | null; labels?: LabelDef[]; size?: number | string }) {
  const url = itemId ? api.thumbnailUrl(pid, itemId) : null
  const [empty, setEmpty] = useState(false)
  return (
    <span className="thumb" data-empty={!itemId || empty || undefined} style={{ width: size, height: size }}>
      {!itemId ? <Placeholder /> : url ? <ServedThumb url={url} onEmpty={setEmpty} /> : <MockThumb itemId={itemId} labels={labels} onEmpty={setEmpty} />}
    </span>
  )
}

/** Thumbnails 404 until the background job made them; a finished thumbnail job retries (epoch) */
function ServedThumb({ url, onEmpty }: { url: string; onEmpty: (empty: boolean) => void }) {
  const epoch = useConnection((s) => s.thumbEpoch)
  const [failed, setFailed] = useState<number | null>(null)
  const isEmpty = failed === epoch
  useEffect(() => onEmpty(isEmpty), [isEmpty, onEmpty])
  if (isEmpty) return <Placeholder />
  return (
    <img
      key={epoch}
      src={epoch ? `${url}?v=${epoch}` : url}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailed(epoch)}
    />
  )
}

function MockThumb({ itemId, labels, onEmpty }: { itemId: string; labels?: LabelDef[]; onEmpty: (empty: boolean) => void }) {
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
  useEffect(() => onEmpty(missing), [missing, onEmpty])
  if (missing) return <Placeholder />
  return <canvas ref={ref} width={64} height={64} />
}
