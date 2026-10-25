// Display-only 3D settings; no image or segmentation data changes.
import type { Scene3DOptions, Vec3 } from './types'

export const DEFAULT_SCENE_3D: Scene3DOptions = {
  background: 'slicer', annotations: 'basic', bounds: true, axisLabels: true,
  orientationCube: true, axes: false,
  planes: { axial: 'off', sagittal: 'off', coronal: 'off' },
}

export function sceneDetail(level: 'minimal' | 'standard' | 'full'): Partial<Scene3DOptions> {
  const detailed = level === 'full'
  return {
    annotations: level === 'minimal' ? 'none' : detailed ? 'full' : 'basic',
    bounds: level !== 'minimal', axisLabels: level !== 'minimal',
    orientationCube: level !== 'minimal', axes: detailed,
    planes: { axial: detailed ? 'outline' : 'off', sagittal: detailed ? 'outline' : 'off', coronal: detailed ? 'outline' : 'off' },
  }
}

/** Four RAS-fraction corners of a slice, shared by the image plane and its outline. */
export function planeCorners(axis: 0 | 1 | 2, position: number): Vec3[] {
  const other = ([0, 1, 2] as const).filter((a) => a !== axis)
  return [[0, 0], [1, 0], [1, 1], [0, 1]].map(([u, v]) => {
    const p: Vec3 = [0, 0, 0]
    p[axis] = position
    p[other[0]!] = u!
    p[other[1]!] = v!
    return p
  })
}

/** World mm to tile-local device pixels, with homogeneous division. */
export function project3D(m: ArrayLike<number>, p: Vec3, width: number, height: number): [number, number] | null {
  const v = [0, 1, 2, 3].map((r) => m[r]! * p[0] + m[4 + r]! * p[1] + m[8 + r]! * p[2] + m[12 + r]!)
  if (!Number.isFinite(v[3]) || Math.abs(v[3]!) < 1e-8) return null
  return [(v[0]! / v[3]! + 1) * width / 2, (1 - v[1]! / v[3]!) * height / 2]
}
