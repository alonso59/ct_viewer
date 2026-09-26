// Shared UI primitives on Radix, styled by tokens (ADR-0008). No domain logic.
import * as RDialog from '@radix-ui/react-dialog'
import * as RTooltip from '@radix-ui/react-tooltip'
import { forwardRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react'

import { Icon, type IconSpec } from '../theme'
import { parseNum } from './format'

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

type NumberInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type' | 'min' | 'max' | 'step'> & {
  value: number | string | null | undefined
  /** `n` = the parsed number (null while empty or not a number), `text` = what was typed */
  onChange: (n: number | null, text: string) => void
  min?: number
  max?: number
  step?: number
}

/** A number field that shows a point and accepts `,` or `.` on every machine (AUD-A3-04): a text
 *  input with `inputmode="decimal"` and spin-button semantics; ↑/↓ step by `step` within min/max. */
export function NumberInput({ value, onChange, min, max, step = 1, onKeyDown, ...rest }: NumberInputProps) {
  const shown = value == null ? '' : String(value)
  const [text, setText] = useState(shown)
  const [pushed, setPushed] = useState(shown)
  if (shown !== pushed) {
    // the value changed from outside: show it, unless it is what the current text already means
    setPushed(shown)
    if (parseNum(text) !== parseNum(shown) || shown === '') setText(shown)
  }
  const n = parseNum(text)
  const commit = (t: string) => {
    setText(t)
    onChange(parseNum(t), t)
  }
  const key = (e: KeyboardEvent<HTMLInputElement>) => {
    onKeyDown?.(e)
    if (e.defaultPrevented || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return
    e.preventDefault()
    const digits = (String(step).split('.')[1] ?? '').length
    let next = (n ?? 0) + (e.key === 'ArrowUp' ? step : -step)
    if (min !== undefined) next = Math.max(min, next)
    if (max !== undefined) next = Math.min(max, next)
    commit(String(Number(next.toFixed(digits))))
  }
  return (
    <input
      {...rest}
      type="text"
      inputMode="decimal"
      role="spinbutton"
      autoComplete="off"
      aria-valuenow={n ?? undefined}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-invalid={rest['aria-invalid'] ?? (text.trim() !== '' && n === null ? true : undefined)}
      value={text}
      onChange={(e) => commit(e.target.value)}
      onKeyDown={key}
    />
  )
}
