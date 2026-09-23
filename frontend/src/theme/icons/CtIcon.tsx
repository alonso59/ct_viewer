/*
 * Custom CT icon set (UI-15), drawn to codicon rules:
 * 16×16 grid, currentColor only, 1 px stroke on half-pixel coordinates,
 * square caps, mitered joins; planes use a 40 % currentColor fill.
 */
import type { SVGProps } from 'react'

type Shape =
  | { d: string; kind?: 'stroke' }
  | { d: string; kind: 'fill' }
  | { d: string; kind: 'tint' }

const CUBE =
  'M2.5 5.5h8v8h-8z M5.5 2.5h8v8h-8z M2.5 5.5l3-3 M10.5 5.5l3-3 M10.5 13.5l3-3 M2.5 13.5l3-3'

const s = (d: string): Shape => ({ d })
const f = (d: string): Shape => ({ d, kind: 'fill' })
const t = (d: string): Shape => ({ d, kind: 'tint' })

export const CT_ICONS = {
  'plane-axial': [s(CUBE), t('M2.5 9.5h8l3-3h-8z'), s('M2.5 9.5h8l3-3h-8z')],
  'plane-sagittal': [s(CUBE), t('M6.5 5.5v8l3-3v-8z'), s('M6.5 5.5v8l3-3v-8z')],
  'plane-coronal': [s(CUBE), t('M4 4h8v8H4z'), s('M4 4h8v8H4z')],
  'view-3d': [s(CUBE), t('M2.5 5.5l3-3h8l-3 3z M10.5 5.5l3-3v8l-3 3z')],
  'window-level': [s('M8 2.5a5.5 5.5 0 1 1 0 11a5.5 5.5 0 1 1 0-11z'), f('M8 2.5a5.5 5.5 0 0 0 0 11z')],
  crosshair: [
    s('M8 3.5a4.5 4.5 0 1 1 0 9a4.5 4.5 0 1 1 0-9z'),
    s('M8 .5v4 M8 11.5v4 M.5 8h4 M11.5 8h4'),
  ],
  'crosshair-lines': [s('M8 1.5v4.5 M8 10v4.5 M1.5 8H6 M10 8h4.5'), f('M7.25 7.25h1.5v1.5h-1.5z')],
  'layout-four-up': [s('M1.5 1.5h13v13h-13z M8 1.5v13 M1.5 8h13')],
  'layout-conventional': [s('M1.5 1.5h13v13h-13z M10.5 1.5v13 M10.5 5.83h4 M10.5 10.17h4')],
  'layout-three-mpr': [s('M1.5 3.5h13v9h-13z M5.83 3.5v9 M10.17 3.5v9')],
  'layout-one-up': [s('M1.5 1.5h13v13h-13z'), s('M10.5 4.5h1v1')],
  'label-overlay': [
    t('M4 3.5c2-1.5 6-1.5 8 0.5s2 6-.5 8s-6.5 2-8.5 0s-1-7 1-8.5z'),
    s('M4 3.5c2-1.5 6-1.5 8 0.5s2 6-.5 8s-6.5 2-8.5 0s-1-7 1-8.5z'),
  ],
  'label-outline': [s('M4 3.5c2-1.5 6-1.5 8 0.5s2 6-.5 8s-6.5 2-8.5 0s-1-7 1-8.5z')],
  'voi-left': [
    s('M1.5 4.5v-3h3 M11.5 1.5h3v3 M14.5 11.5v3h-3 M4.5 14.5h-3v-3'),
    s('M6.5 4.5v7h3.5'),
  ],
  'voi-right': [
    s('M1.5 4.5v-3h3 M11.5 1.5h3v3 M14.5 11.5v3h-3 M4.5 14.5h-3v-3'),
    s('M6 11.5v-7h2.5a1.75 1.75 0 0 1 0 3.5H6 M8.25 8l2 3.5'),
  ],
  'slice-stack': [s('M2.5 10.5l5.5 3l5.5-3 M2.5 8l5.5 3l5.5-3'), t('M2.5 5.5L8 2.5l5.5 3L8 8.5z'), s('M2.5 5.5L8 2.5l5.5 3L8 8.5z')],
} satisfies Record<string, Shape[]>

export type CtIconName = keyof typeof CT_ICONS

export interface CtIconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: CtIconName
  size?: number
  title?: string
}

export function CtIcon({ name, size = 16, title, ...rest }: CtIconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {CT_ICONS[name].map((shape, i) =>
        shape.kind === 'fill' ? (
          <path key={i} d={shape.d} fill="currentColor" />
        ) : shape.kind === 'tint' ? (
          <path key={i} d={shape.d} fill="currentColor" fillOpacity={0.4} />
        ) : (
          <path
            key={i}
            d={shape.d}
            fill="none"
            stroke="currentColor"
            strokeWidth={1}
            strokeLinecap="square"
            strokeLinejoin="miter"
          />
        ),
      )}
    </svg>
  )
}
