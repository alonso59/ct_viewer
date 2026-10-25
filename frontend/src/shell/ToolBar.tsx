import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { registry } from './registry'

/** QuPath-style tool bar. Items are contributed by features, e.g. the viewer. */
export function ToolBar() {
  const { t } = useTranslation()
  const bar = useRef<HTMLDivElement>(null)
  // A mouse wheel over the bar scrolls it sideways, so tools cut off on a narrow window are reachable
  const wheel = (e: React.WheelEvent) => {
    const el = bar.current
    if (el && el.scrollWidth > el.clientWidth && Math.abs(e.deltaY) > Math.abs(e.deltaX)) el.scrollLeft += e.deltaY
  }
  return (
    <div className="toolbar" role="toolbar" aria-label={t('shell.toolbar')} ref={bar} onWheel={wheel}>
      {registry.tools.map(({ id, component: C }) => (
        <C key={id} />
      ))}
    </div>
  )
}
