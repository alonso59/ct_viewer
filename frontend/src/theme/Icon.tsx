import type { HTMLAttributes } from 'react'

import { CtIcon, type CtIconName } from './icons/CtIcon'

// One icon API for both sets: codicons (`name`) and the custom CT set (`ct`). UI-15.
export type IconSpec = { codicon: string } | { ct: CtIconName }

export function Icon({
  spec,
  size = 16,
  className,
  ...rest
}: { spec: IconSpec; size?: number } & HTMLAttributes<HTMLElement>) {
  if ('ct' in spec) return <CtIcon name={spec.ct} size={size} className={className} />
  return (
    <i
      aria-hidden
      className={`codicon codicon-${spec.codicon}${className ? ` ${className}` : ''}`}
      style={size === 16 ? undefined : { fontSize: size }}
      {...rest}
    />
  )
}

export const codicon = (name: string): IconSpec => ({ codicon: name })
export const ct = (name: CtIconName): IconSpec => ({ ct: name })
