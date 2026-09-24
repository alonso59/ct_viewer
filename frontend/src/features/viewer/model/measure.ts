// VW-17 measurement math on RAS mm points (pure; the engine gives points and ROI statistics).
import type { Plane, RoiStats, Vec3 } from './types'

export type MeasureKind = 'distance' | 'angle' | 'roi'

export interface Measurement {
  id: number
  kind: MeasureKind
  tile: Plane
  /** 1-based slice index of `tile` when drawn; shown only on that slice */
  slice: number
  points: Vec3[]
  stats?: RoiStats | null
}

/** Points a measurement needs before it is complete */
export const NEEDED: Record<MeasureKind, number> = { distance: 2, angle: 3, roi: 2 }

export const distanceMm = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])

/** Angle at the middle point, in degrees */
export function angleDeg(a: Vec3, vertex: Vec3, b: Vec3): number {
  const u = [a[0] - vertex[0], a[1] - vertex[1], a[2] - vertex[2]]
  const v = [b[0] - vertex[0], b[1] - vertex[1], b[2] - vertex[2]]
  const nu = Math.hypot(...u)
  const nv = Math.hypot(...v)
  if (!nu || !nv) return 0
  const cos = Math.max(-1, Math.min(1, (u[0]! * v[0]! + u[1]! * v[1]! + u[2]! * v[2]!) / (nu * nv)))
  return (Math.acos(cos) * 180) / Math.PI
}
