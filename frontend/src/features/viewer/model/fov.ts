// Per-view 2D field of view (VW-06/26): pan in mm + zoom per plane, optionally linked.
// Pure so the engine's linking rules can be tested without WebGL.
import { PLANES } from './layouts'
import type { Plane } from './types'

/** [pan x, pan y, pan z in mm, zoom] as NiiVue's `pan2Dxyzmm` */
export type Fov = [number, number, number, number]
export type FovMap = Partial<Record<Plane, Fov>>

export const FIT: Readonly<Fov> = [0, 0, 0, 1]
export const ZOOM_MIN = 0.5
export const ZOOM_MAX = 16

export const fovOf = (m: FovMap, plane: Plane): Fov => [...(m[plane] ?? FIT)] as Fov

export const zoomed = (p: Fov, factor: number): Fov => [p[0], p[1], p[2], Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, p[3] * factor))]

/** Set one plane's field of view; linked zoom writes it to every 2D view (VW-06) */
export function setFov(m: FovMap, plane: Plane, p: Fov, linked: boolean): void {
  for (const pl of linked ? PLANES : [plane]) m[pl] = [...p] as Fov
}

/** VW-26 fit on a 2D view: zoom 100 %, zero pan; linked zoom fits all 2D views */
export function fitFov(m: FovMap, plane: Plane, linked: boolean): void {
  setFov(m, plane, [...FIT] as Fov, linked)
}

/** Turning the link on copies the last-used view's field of view to the others (VW-06) */
export function linkFov(m: FovMap, from: Plane): void {
  setFov(m, from, fovOf(m, from), true)
}
