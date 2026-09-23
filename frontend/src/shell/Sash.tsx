import { useRef, useState } from 'react'

/** Drag handle between regions. `onDrag` receives the pixel delta since the drag started. */
export function Sash({ direction, onStart, onDrag }: {
  direction: 'v' | 'h'
  onStart: () => void
  onDrag: (delta: number) => void
}) {
  const origin = useRef(0)
  const [dragging, setDragging] = useState(false)
  return (
    <div
      className={`sash sash-${direction}`}
      data-dragging={dragging}
      role="separator"
      aria-orientation={direction === 'v' ? 'vertical' : 'horizontal'}
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
