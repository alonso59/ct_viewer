// VW-27: scene guides stay in world geometry; planes use the slider fraction for their own axis.
import { planeCorners, project3D, sceneDetail } from './scene3d'

test('each plane moves only along its normal and spans the complete volume', () => {
  for (const axis of [0, 1, 2] as const) {
    const corners = planeCorners(axis, 0.37)
    expect(corners).toHaveLength(4)
    expect(corners.every((c) => c[axis] === 0.37)).toBe(true)
    for (const other of [0, 1, 2].filter((a) => a !== axis)) expect(new Set(corners.map((c) => c[other]))).toEqual(new Set([0, 1]))
  }
})

test('projection honors camera transform, perspective division and viewport aspect ratio', () => {
  const matrix = [2,0,0,0, 0,3,0,0, 0,0,1,0, 1,-1,0,2]
  expect(project3D(matrix, [0,0,0], 200,100)).toEqual([150,75])
  expect(project3D(matrix, [0.5,0.5,0], 200,100)).toEqual([200,37.5])
  expect(project3D(new Array(16).fill(0), [1,2,3],100,100)).toBeNull()
  expect(sceneDetail('minimal').planes).toEqual({ axial:'off', sagittal:'off', coronal:'off' })
})
