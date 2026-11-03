import { useRef, useState } from 'react'

/** Pixels an arrow key moves a sash */
export const SASH_STEP = 16

/** Drag handle between regions. `onDrag` receives the pixel delta since the drag started; an arrow
 *  key is a drag of `SASH_STEP` in its direction, Enter restores the default size. */
export function Sash({ direction, label, value, min, max, onStart, onDrag, onReset }: {
  direction: 'v' | 'h'
  label: string
  /** Size of the region it resizes, in px */
  value: number
  min: number
  max: number
  onStart: () => void
  onDrag: (delta: number) => void
  onReset: () => void
}) {
  const origin = useRef(0)
  const [dragging, setDragging] = useState(false)
  const keys: Record<string, number> = direction === 'v' ? { ArrowLeft: -SASH_STEP, ArrowRight: SASH_STEP } : { ArrowUp: -SASH_STEP, ArrowDown: SASH_STEP }
  return (
    <div
      className={`sash sash-${direction}`}
      data-dragging={dragging}
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation={direction === 'v' ? 'vertical' : 'horizontal'}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      onKeyDown={(e) => {
        const delta = keys[e.key]
        if (delta !== undefined) {
          e.preventDefault()
          onStart()
          onDrag(delta)
        } else if (e.key === 'Enter') {
          e.preventDefault()
          onReset()
        }
      }}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        origin.current = direction === 'v' ? e.clientX : e.clientY
        setDragging(true)
        onStart()
      }}
      onPointerMove={(e) => {
        if (!dragging) return
        onDrag((direction === 'v' ? e.clientX : e.clientY) - origin.current)
      }}
      onPointerUp={() => setDragging(false)}
    />
  )
}
