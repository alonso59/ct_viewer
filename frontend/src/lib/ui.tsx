// Shared UI primitives on Radix, styled by tokens (ADR-0008). No domain logic.
import * as RDialog from '@radix-ui/react-dialog'
import * as RTooltip from '@radix-ui/react-tooltip'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

import { Icon, type IconSpec } from '../theme'

export function Tooltip({ label, shortcut, children, side = 'bottom' }: {
  label: ReactNode
  shortcut?: string
  children: ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
}) {
  return (
    <RTooltip.Root delayDuration={450}>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content className="overlay tooltip" side={side} sideOffset={6}>
          {label}
          {shortcut ? <span className="kbd" style={{ marginLeft: 8 }}>{shortcut}</span> : null}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  )
}

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: IconSpec
  label: string
  shortcut?: string
  pressed?: boolean
  tooltipSide?: 'top' | 'bottom' | 'left' | 'right'
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { icon, label, shortcut, pressed, tooltipSide, className, ...rest },
  ref,
) {
  return (
    <Tooltip label={label} shortcut={shortcut} side={tooltipSide}>
      <button
        ref={ref}
        type="button"
        className={`icon-btn${className ? ` ${className}` : ''}`}
        aria-label={label}
        aria-pressed={pressed}
        {...rest}
      >
        <Icon spec={icon} />
      </button>
    </Tooltip>
  )
})

export function Dialog({ open, onOpenChange, title, icon, children, footer, size }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  icon?: IconSpec
  children: ReactNode
  footer?: ReactNode
  size?: 'lg'
}) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="dialog-scrim" />
        <RDialog.Content className={`overlay dialog${size === 'lg' ? ' dialog-lg' : ''}`} aria-describedby={undefined}>
          <div className="dialog-header">
            {icon ? <Icon spec={icon} /> : null}
            <RDialog.Title style={{ margin: 0, fontSize: 'var(--fs-ui)', flex: 1 }}>{title}</RDialog.Title>
            <RDialog.Close asChild>
              <button type="button" className="icon-btn" aria-label="close">
                <Icon spec={{ codicon: 'close' }} />
              </button>
            </RDialog.Close>
          </div>
          <div className="dialog-body">{children}</div>
          {footer ? <div className="dialog-footer">{footer}</div> : null}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

export function Progress({ value, total }: { value: number; total: number }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <span style={{ width: `${pct}%` }} />
    </div>
  )
}
