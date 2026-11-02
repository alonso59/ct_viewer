// Shared UI primitives on Radix, styled by tokens. No domain logic.
import * as RDialog from '@radix-ui/react-dialog'
import * as RTooltip from '@radix-ui/react-tooltip'
import { forwardRef, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react'

import { Icon, type IconSpec } from '../theme'
import i18n from '../i18n'
import { fmtInt, parseNum } from './format'

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

export function Dialog({ open, onOpenChange, title, description, icon, children, footer, size, dismissible = true, actions }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  /** One sentence under the title, read as the dialog's description */
  description?: ReactNode
  icon?: IconSpec
  children: ReactNode
  footer?: ReactNode
  size?: 'lg'
  /** false: a click outside does nothing (Escape and × still call `onOpenChange(false)`) */
  dismissible?: boolean
  /** Extra header buttons, before × */
  actions?: ReactNode
}) {
  // Dialogs open from state, not from a Radix trigger: closing gives focus back to the control
  // that had it when the dialog opened
  const invoker = useRef<HTMLElement | null>(null)
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="dialog-scrim" />
        <RDialog.Content
          className={`overlay dialog${size === 'lg' ? ' dialog-lg' : ''}`}
          {...(description ? {} : { 'aria-describedby': undefined })}
          onInteractOutside={dismissible ? undefined : (e) => e.preventDefault()}
          onOpenAutoFocus={() => {
            invoker.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
          }}
          onCloseAutoFocus={(e) => {
            const back = invoker.current
            invoker.current = null
            if (!back?.isConnected) return
            e.preventDefault()
            back.focus()
          }}
        >
          <div className="dialog-header">
            {icon ? <Icon spec={icon} /> : null}
            <RDialog.Title style={{ margin: 0, fontSize: 'var(--fs-ui)', flex: 1 }}>{title}</RDialog.Title>
            {actions}
            <RDialog.Close asChild>
              <button type="button" className="icon-btn" aria-label={i18n.t('common.close')}>
                <Icon spec={{ codicon: 'close' }} />
              </button>
            </RDialog.Close>
          </div>
          <div className="dialog-body">
            {description ? <RDialog.Description className="muted dialog-description">{description}</RDialog.Description> : null}
            {children}
          </div>
          {footer ? <div className="dialog-footer">{footer}</div> : null}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}

/** A button that says why it is disabled: tooltip and accessible description (`reason`, shown only
 *  while disabled) */
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { reason?: string | null }>(function Button(
  { reason, disabled, title, ...rest },
  ref,
) {
  const id = useId()
  const why = disabled && reason ? reason : undefined
  return (
    <>
      <button ref={ref} type="button" {...rest} disabled={disabled} title={why ?? title} aria-describedby={why ? id : rest['aria-describedby']} />
      {why ? <span id={id} className="visually-hidden">{why}</span> : null}
    </>
  )
})

/**
 * A costly or destructive action asks inline before it runs: the trigger gives way to the
 * question, a danger-styled confirm and a keep button. Focus moves to the confirm and returns
 * to the trigger when kept; Escape keeps.
 */
export function ConfirmInline({ question, confirm, keep, onConfirm, trigger }: {
  question: string
  confirm: string
  keep?: string
  onConfirm: () => void
  /** Renders the trigger; call `ask` to show the question */
  trigger: (ask: () => void) => ReactNode
}) {
  const [asking, setAsking] = useState(false)
  const box = useRef<HTMLSpanElement>(null)
  const asked = useRef(false)
  useEffect(() => {
    if (asking) box.current?.querySelector<HTMLButtonElement>('.btn-danger')?.focus()
    else if (asked.current) box.current?.querySelector<HTMLElement>('button')?.focus()
    asked.current = asking
  }, [asking])
  return (
    <span ref={box} className="confirm-inline">
      {asking ? (
        <span role="group" aria-label={question} onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setAsking(false) } }}>
          <span role="note">{question}</span>
          <button type="button" className="btn btn-sm btn-danger" onClick={() => { setAsking(false); onConfirm() }}>{confirm}</button>
          <button type="button" className="btn btn-sm" onClick={() => setAsking(false)}>{keep ?? i18n.t('common.keepRunning')}</button>
        </span>
      ) : trigger(() => setAsking(true))}
    </span>
  )
}

/** `label` names the bar for assistive technology ("Indexing"); the value reads "86 of 187" */
export function Progress({ value, total, label, stale }: { value: number; total: number; label: string; stale?: boolean }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className="progress" data-stale={stale || undefined} role="progressbar" aria-label={label} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-valuetext={i18n.t('progress.of', { done: fmtInt(value), total: fmtInt(total) })}>
      <span style={{ width: `${pct}%` }} />
    </div>
  )
}

/** A moving bar for work whose total is not known yet */
export function IndeterminateProgress({ label }: { label: string }) {
  return <div className="progress progress-indeterminate" role="progressbar" aria-label={label} aria-busy="true"><span /></div>
}

type NumberInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type' | 'min' | 'max' | 'step'> & {
  value: number | string | null | undefined
  /** `n` = the parsed number (null while empty or not a number), `text` = what was typed */
  onChange: (n: number | null, text: string) => void
  min?: number
  max?: number
  step?: number
}

/** A number field that shows a point and accepts `,` or `.` on every machine: a text
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
