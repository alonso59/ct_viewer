import type { Axis } from '../../services/api'

export interface ContentRect {
  left: number
  top: number
  width: number
  height: number
}

export interface PhysicalFitSize {
  width: number
  height: number
}

export type VoxelSpacing = [number, number, number]

export function normalizeVoxelSpacing(spacing?: readonly number[] | null): VoxelSpacing {
  return [
    positiveSpacingValue(spacing?.[0]),
    positiveSpacingValue(spacing?.[1]),
    positiveSpacingValue(spacing?.[2]),
  ]
}

export function getPhysicalFitSize(
  axis: Axis,
  naturalWidth: number,
  naturalHeight: number,
  spacing?: readonly number[] | null,
): PhysicalFitSize {
  const [spacingX, spacingY, spacingZ] = normalizeVoxelSpacing(spacing)
  const width = Math.max(0, naturalWidth)
  const height = Math.max(0, naturalHeight)

  if (axis === 'axial') {
    return {
      width: width * spacingX,
      height: height * spacingY,
    }
  }

  if (axis === 'coronal') {
    return {
      width: width * spacingX,
      height: height * spacingZ,
    }
  }

  return {
    width: width * spacingY,
    height: height * spacingZ,
  }
}

export function computeContainRect(
  containerWidth: number,
  containerHeight: number,
  contentWidth: number,
  contentHeight: number,
): ContentRect | null {
  if (
    containerWidth <= 0 ||
    containerHeight <= 0 ||
    contentWidth <= 0 ||
    contentHeight <= 0
  ) {
    return null
  }

  const scale = Math.min(containerWidth / contentWidth, containerHeight / contentHeight)
  const renderedWidth = contentWidth * scale
  const renderedHeight = contentHeight * scale

  return {
    left: (containerWidth - renderedWidth) / 2 / containerWidth,
    top: (containerHeight - renderedHeight) / 2 / containerHeight,
    width: renderedWidth / containerWidth,
    height: renderedHeight / containerHeight,
  }
}

function positiveSpacingValue(value: number | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 1
}
