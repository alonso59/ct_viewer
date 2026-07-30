import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Box, CircularProgress, Stack, Typography } from '@mui/material'
import { Bounds, OrbitControls, useBounds } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import axios from 'axios'
import {
  Group,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  type Material,
} from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'

import { apiClient, getApiErrorMessage, isHandleExpiredError } from '../../services/api'
import { getSegmentationColor } from './segmentationPalette'

interface Surface3DViewProps {
  availableLabels: number[]
  blend: number
  crosshairPoint?: VolumePoint | null
  errorText?: string | null
  hasMask: boolean
  labelColors: Record<number, string>
  loadHandle: string | null
  onHandleExpired?: () => void
  spacing?: number[] | null
  visibleLabels: number[]
  volumeShape?: number[] | null
}

interface MeshEntry {
  label: number
  object: Object3D
}

interface VolumePoint {
  x: number
  y: number
  z: number
}

interface VolumeFrame {
  center: [number, number, number]
  size: [number, number, number]
}

const MESH_LOAD_DEFER_MS = 900

function isMeshObject(node: Object3D): node is Mesh {
  return 'isMesh' in node && Boolean((node as { isMesh?: boolean }).isMesh)
}

function toMaterialList(material: Material | Material[]): Material[] {
  return Array.isArray(material) ? material : [material]
}

function disposeObject(root: Object3D): void {
  root.traverse((node) => {
    if (!isMeshObject(node)) {
      return
    }
    node.geometry.dispose()
    toMaterialList(node.material).forEach((material) => material.dispose())
  })
}

function surfaceOpacity(blend: number): number {
  return Math.min(1, Math.max(0, blend))
}

function applyVisualStyle(
  root: Object3D,
  color: string,
  blend: number,
): void {
  const opacity = surfaceOpacity(blend)
  root.traverse((node) => {
    if (!isMeshObject(node)) {
      return
    }

    toMaterialList(node.material).forEach((material) => material.dispose())
    node.material = new MeshStandardMaterial({
      color,
      opacity,
      transparent: opacity < 1,
      roughness: 0.52,
      metalness: 0.02,
      emissive: color,
      emissiveIntensity: 0.05,
      depthWrite: opacity >= 0.95,
    })
    node.castShadow = false
    node.receiveShadow = true
  })
}

function updateMeshVisual(root: Object3D, blend: number): void {
  const opacity = surfaceOpacity(blend)
  root.traverse((node) => {
    if (!isMeshObject(node)) {
      return
    }
    toMaterialList(node.material).forEach((material) => {
      if (material instanceof MeshStandardMaterial) {
        material.opacity = opacity
        material.transparent = opacity < 1
        material.depthWrite = opacity >= 0.95
        material.needsUpdate = true
      }
    })
  })
}

function validVolumeFrame(shape?: number[] | null, spacing?: number[] | null): VolumeFrame | null {
  if (!shape || !spacing || shape.length < 3 || spacing.length < 3) {
    return null
  }
  const size = [0, 1, 2].map((index) =>
    Math.max(Number(spacing[index]) || 1, (Math.max(1, Number(shape[index]) || 1) - 1) * (Number(spacing[index]) || 1)),
  ) as [number, number, number]
  return {
    center: [size[0] / 2, size[1] / 2, size[2] / 2],
    size,
  }
}

function volumePointToWorld(
  point: VolumePoint | null | undefined,
  shape?: number[] | null,
  spacing?: number[] | null,
): [number, number, number] | null {
  if (!point || !shape || !spacing || shape.length < 3 || spacing.length < 3) {
    return null
  }

  return [
    Math.min(Math.max(point.x, 0), Math.max(0, shape[0] - 1)) * (Number(spacing[0]) || 1),
    Math.min(Math.max(point.y, 0), Math.max(0, shape[1] - 1)) * (Number(spacing[1]) || 1),
    Math.min(Math.max(point.z, 0), Math.max(0, shape[2] - 1)) * (Number(spacing[2]) || 1),
  ]
}

async function loadMesh(
  label: number,
  color: string,
  blend: number,
  loadHandle: string,
  signal?: AbortSignal,
): Promise<MeshEntry | null> {
  try {
    const blob = await apiClient.getMeshBlob(label, loadHandle, true, { signal })
    const objectUrl = URL.createObjectURL(blob)
    try {
      const loader = new GLTFLoader()
      const gltf = await loader.loadAsync(objectUrl)
      const object = gltf.scene
      object.userData.surfaceLabel = label
      applyVisualStyle(object, color, blend)
      return { label, object }
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null
    }
    throw error
  }
}

function Surface3DViewComponent({
  availableLabels,
  blend,
  crosshairPoint,
  errorText,
  hasMask,
  labelColors,
  loadHandle,
  onHandleExpired,
  spacing,
  visibleLabels,
  volumeShape,
}: Surface3DViewProps) {
  const [requestState, setRequestState] = useState<{
    error: string | null
    loadingLabels: number[]
    meshesByLabel: Record<number, MeshEntry>
    failedLabels: Set<number>
    seriesKey: string | null
  }>({
    error: null,
    loadingLabels: [],
    meshesByLabel: {},
    failedLabels: new Set(),
    seriesKey: null,
  })
  const [deferredMeshLoadKey, setDeferredMeshLoadKey] = useState<string | null>(null)
  const [fitTick, setFitTick] = useState(0)
  const inFlightRef = useRef(new Map<number, AbortController>())
  const meshesRef = useRef<Record<number, MeshEntry>>({})

  const sortedVisibleLabels = useMemo(
    () => [...visibleLabels].sort((left, right) => left - right),
    [visibleLabels],
  )
  const sortedAvailableLabels = useMemo(
    () => [...availableLabels].sort((left, right) => left - right),
    [availableLabels],
  )
  const seriesKey = loadHandle && hasMask ? loadHandle : null
  const visibleLabelsKey = sortedVisibleLabels.join(',')
  const meshLoadKey = seriesKey && visibleLabelsKey ? `${seriesKey}:${visibleLabelsKey}` : null
  const referencePoint = useMemo(
    () => volumePointToWorld(crosshairPoint, volumeShape, spacing),
    [crosshairPoint, spacing, volumeShape],
  )
  const volumeFrame = useMemo(() => validVolumeFrame(volumeShape, spacing), [spacing, volumeShape])

  useEffect(() => {
    meshesRef.current = requestState.meshesByLabel
  }, [requestState.meshesByLabel])

  useEffect(() => {
    setDeferredMeshLoadKey(null)
    if (!meshLoadKey) {
      return
    }

    const timeout = window.setTimeout(() => {
      setDeferredMeshLoadKey(meshLoadKey)
    }, MESH_LOAD_DEFER_MS)
    return () => window.clearTimeout(timeout)
  }, [meshLoadKey])

  useEffect(() => {
    setRequestState((current) => {
      if (current.seriesKey === seriesKey) {
        return current
      }
      inFlightRef.current.forEach((controller) => controller.abort())
      inFlightRef.current.clear()
      Object.values(current.meshesByLabel).forEach((entry) => disposeObject(entry.object))
      return {
        error: null,
        loadingLabels: [],
        meshesByLabel: {},
        failedLabels: new Set(),
        seriesKey,
      }
    })
  }, [seriesKey])

  useEffect(() => {
    if (
      !seriesKey ||
      sortedVisibleLabels.length === 0 ||
      deferredMeshLoadKey !== meshLoadKey
    ) {
      return
    }

    const missingLabels = sortedVisibleLabels.filter(
      (label) =>
        !requestState.meshesByLabel[label] &&
        !requestState.loadingLabels.includes(label) &&
        !requestState.failedLabels.has(label) &&
        !inFlightRef.current.has(label),
    )
    if (missingLabels.length === 0) {
      return
    }

    setRequestState((current) => ({
      ...current,
      error: null,
      loadingLabels: Array.from(new Set([...current.loadingLabels, ...missingLabels])),
    }))

    missingLabels.forEach((label) => {
      const controller = new AbortController()
      inFlightRef.current.set(label, controller)
      const color = labelColors[label] ?? getSegmentationColor(label)

      loadMesh(label, color, 1, seriesKey, controller.signal)
        .then((entry) => {
          inFlightRef.current.delete(label)
          let shouldFit = false
          setRequestState((current) => {
            const nextLoadingLabels = current.loadingLabels.filter((value) => value !== label)
            if (current.seriesKey !== seriesKey) {
              if (entry) {
                disposeObject(entry.object)
              }
              return {
                ...current,
                loadingLabels: nextLoadingLabels,
              }
            }
            if (entry) {
              shouldFit = Object.keys(current.meshesByLabel).length === 0
            }
            return {
              ...current,
              error: null,
              loadingLabels: nextLoadingLabels,
              meshesByLabel: entry
                ? {
                    ...current.meshesByLabel,
                    [label]: entry,
                  }
                : current.meshesByLabel,
            }
          })
          if (shouldFit) {
            setFitTick((current) => current + 1)
          }
        })
        .catch((requestError) => {
          inFlightRef.current.delete(label)
          if (axios.isAxiosError(requestError) && requestError.code === 'ERR_CANCELED') {
            setRequestState((current) => ({
              ...current,
              loadingLabels: current.loadingLabels.filter((value) => value !== label),
            }))
            return
          }
          if (isHandleExpiredError(requestError)) {
            onHandleExpired?.()
            return
          }
          setRequestState((current) => ({
            ...current,
            error: getApiErrorMessage(requestError),
            loadingLabels: current.loadingLabels.filter((value) => value !== label),
            failedLabels: new Set([...current.failedLabels, label]),
          }))
        })
    })
  }, [
    labelColors,
    deferredMeshLoadKey,
    meshLoadKey,
    onHandleExpired,
    requestState.failedLabels,
    requestState.loadingLabels,
    requestState.meshesByLabel,
    seriesKey,
    sortedVisibleLabels,
    surface3dEnabled,
  ])

  useEffect(() => {
    Object.values(requestState.meshesByLabel).forEach((entry) =>
      updateMeshVisual(entry.object, blend),
    )
  }, [blend, requestState.meshesByLabel])

  useEffect(() => {
    const inFlightControllers = inFlightRef.current
    return () => {
      inFlightControllers.forEach((controller) => controller.abort())
      inFlightControllers.clear()
      Object.values(meshesRef.current).forEach((entry) => disposeObject(entry.object))
    }
  }, [])

  if (errorText) {
    return (
      <Alert severity="warning" sx={{ m: 2 }}>
        {errorText}
      </Alert>
    )
  }

  if (!loadHandle) {
    return (
      <SurfacePanelMessage
        title="Select a series"
        description="Choose a series to initialize the 3D surface view."
      />
    )
  }

  if (!hasMask) {
    return (
      <SurfacePanelMessage
        title="No segmentation available"
        description="This series does not include a segmentation mask for 3D surfaces."
      />
    )
  }

  if (sortedAvailableLabels.length === 0) {
    return (
      <SurfacePanelMessage
        title="Empty segmentation mask"
        description="The loaded segmentation file does not contain any visible labels."
      />
    )
  }

  if (sortedVisibleLabels.length === 0) {
    return (
      <SurfacePanelMessage
        title="All layers hidden"
        description="Enable at least one structure to render the 3D surface."
      />
    )
  }

  if (!surface3dEnabled) {
    return (
      <SurfacePanelMessage
        title="3D surface disabled"
        description="Click Enable 3D to load meshes."
        action={
          <Button
            size="small"
            variant="outlined"
            onClick={() => setSurface3dEnabled(true)}
            sx={{ mt: 1 }}
          >
            Enable 3D
          </Button>
        }
      />
    )
  }

  const renderedMeshes = sortedVisibleLabels
    .map((label) => requestState.meshesByLabel[label] ?? null)
    .filter((entry): entry is MeshEntry => entry !== null)
  const isLoading = requestState.loadingLabels.length > 0
  const loadError = requestState.error
  const hasBlockingLoadError = Boolean(loadError) && renderedMeshes.length === 0

  return (
    <Box
      data-surface-3d="panel"
      data-surface-blend={blend.toFixed(2)}
      data-surface-labels={sortedVisibleLabels.join(',')}
      data-surface-loading={isLoading ? 'true' : 'false'}
      sx={{
        position: 'relative',
        flex: 1,
        minHeight: 0,
        minWidth: 0,
        borderRadius: 3,
        overflow: 'hidden',
        border: '1px solid',
        borderColor: 'rgba(119, 92, 168, 0.38)',
        background:
          'linear-gradient(180deg, #b7bfd9 0%, #9fa8c8 52%, #858cad 100%)',
      }}
    >
      {hasBlockingLoadError ? (
        <Alert severity="error" sx={{ m: 2 }}>
          3D surface generation failed: {loadError}
        </Alert>
      ) : (
        <Canvas
          dpr={[1, 1.8]}
          camera={{
            far: 5000,
            fov: 42,
            near: 0.1,
            position: [300, 240, 300],
          }}
          gl={{ antialias: true }}
          style={{ width: '100%', height: '100%' }}
        >
          <SurfaceScene
            fitTick={fitTick}
            meshes={renderedMeshes}
            referencePoint={referencePoint}
            volumeFrame={volumeFrame}
          />
        </Canvas>
      )}
      {!hasBlockingLoadError ? <OrientationLabels /> : null}

      {!hasBlockingLoadError && loadError ? (
        <Alert
          severity="warning"
          sx={{
            position: 'absolute',
            left: 12,
            right: 12,
            bottom: 12,
            py: 0.1,
            '& .MuiAlert-message': {
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            },
          }}
        >
          Surface refresh failed. Keeping the previous mesh on screen.
        </Alert>
      ) : null}

      {isLoading ? (
        <Stack
          spacing={1}
          alignItems="center"
          justifyContent="center"
          sx={{
            position: 'absolute',
            inset: 0,
            backgroundColor: 'rgba(65, 70, 105, 0.22)',
            pointerEvents: 'none',
          }}
        >
          <CircularProgress size={26} />
          <Typography variant="caption" color="text.secondary">
            Generating 3D surface...
          </Typography>
        </Stack>
      ) : null}
    </Box>
  )
}

function SurfaceScene({
  fitTick,
  meshes,
  referencePoint,
  volumeFrame,
}: {
  fitTick: number
  meshes: MeshEntry[]
  referencePoint: [number, number, number] | null
  volumeFrame: VolumeFrame | null
}) {
  const controlsRef = useRef<OrbitControlsImpl | null>(null)
  const groupRef = useRef<Group | null>(null)

  return (
    <>
      <color attach="background" args={['#aeb7d2']} />
      <fog attach="fog" args={['#aeb7d2', 720, 2400]} />
      <ambientLight intensity={0.72} />
      <hemisphereLight args={['#f8fbff', '#7d86ad', 0.9]} />
      <directionalLight position={[260, 360, 180]} intensity={1.05} />
      <directionalLight position={[-180, 140, -220]} intensity={0.42} color="#f2f5ff" />
      <Bounds fit clip margin={1.1}>
        <group ref={groupRef}>
          <VolumeReferenceFrame frame={volumeFrame} />
          <CrosshairGuides frame={volumeFrame} point={referencePoint} />
          {meshes.map((entry) => (
            <primitive key={entry.label} object={entry.object} />
          ))}
        </group>
        <SceneCameraController
          controlsRef={controlsRef}
          fitTick={fitTick}
          meshCount={meshes.length}
          targetRef={groupRef}
        />
      </Bounds>
      <OrbitControls
        ref={controlsRef}
        enableDamping
        dampingFactor={0.08}
        rotateSpeed={0.8}
        screenSpacePanning
      />
    </>
  )
}

function SceneCameraController({
  controlsRef,
  fitTick,
  meshCount,
  targetRef,
}: {
  controlsRef: React.RefObject<OrbitControlsImpl | null>
  fitTick: number
  meshCount: number
  targetRef: React.RefObject<Group | null>
}) {
  const bounds = useBounds()

  useEffect(() => {
    if (!targetRef.current || meshCount === 0) {
      return
    }
    bounds.refresh(targetRef.current).clip().fit()
    controlsRef.current?.update()
  }, [bounds, controlsRef, fitTick, meshCount, targetRef])

  return null
}

function VolumeReferenceFrame({ frame }: { frame: VolumeFrame | null }) {
  if (!frame) {
    return null
  }

  return (
    <mesh position={frame.center}>
      <boxGeometry args={frame.size} />
      <meshBasicMaterial color="#bf53d9" transparent opacity={0.22} wireframe />
    </mesh>
  )
}

function CrosshairGuides({
  frame,
  point,
}: {
  frame: VolumeFrame | null
  point: [number, number, number] | null
}) {
  if (!frame || !point) {
    return null
  }

  const [x, y, z] = point
  const [width, height, depth] = frame.size
  const lineThickness = Math.max(0.6, Math.min(width, height, depth) * 0.004)

  return (
    <group>
      <ReferenceSlab
        color="#fb923c"
        opacity={0.84}
        position={[frame.center[0], y, z]}
        size={[width, lineThickness, lineThickness]}
      />
      <ReferenceSlab
        color="#22c55e"
        opacity={0.84}
        position={[x, frame.center[1], z]}
        size={[lineThickness, height, lineThickness]}
      />
      <ReferenceSlab
        color="#ef4444"
        opacity={0.84}
        position={[x, y, frame.center[2]]}
        size={[lineThickness, lineThickness, depth]}
      />
      <mesh position={point}>
        <sphereGeometry args={[lineThickness * 2.2, 20, 12]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.92} />
      </mesh>
    </group>
  )
}

function ReferenceSlab({
  color,
  opacity,
  position,
  size,
}: {
  color: string
  opacity: number
  position: [number, number, number]
  size: [number, number, number]
}) {
  return (
    <mesh position={position}>
      <boxGeometry args={size} />
      <meshBasicMaterial
        color={color}
        depthWrite={false}
        transparent
        opacity={opacity}
      />
    </mesh>
  )
}

function OrientationLabels() {
  const labelSx = {
    color: 'rgba(255,255,255,0.88)',
    fontWeight: 800,
    lineHeight: 1,
    position: 'absolute',
    textShadow: '0 1px 4px rgba(45, 36, 74, 0.55)',
    zIndex: 2,
    pointerEvents: 'none',
    userSelect: 'none',
  } as const

  return (
    <>
      <Typography variant="body2" data-orientation-label="S" sx={{ ...labelSx, top: 12, left: '50%' }}>
        S
      </Typography>
      <Typography variant="body2" data-orientation-label="R" sx={{ ...labelSx, left: 12, top: '50%' }}>
        R
      </Typography>
      <Typography variant="body2" data-orientation-label="L" sx={{ ...labelSx, right: 12, top: '50%' }}>
        L
      </Typography>
      <Typography variant="body2" data-orientation-label="I" sx={{ ...labelSx, bottom: 12, left: '50%' }}>
        I
      </Typography>
    </>
  )
}

function SurfacePanelMessage({
  action,
  description,
  title,
}: {
  action?: ReactNode
  description: string
  title: string
}) {
  return (
    <Box
      sx={{
        flex: 1,
        minHeight: 0,
        borderRadius: 3,
        border: '1px dashed',
        borderColor: 'rgba(119, 92, 168, 0.38)',
        background:
          'linear-gradient(180deg, rgba(183,191,217,0.28) 0%, rgba(133,140,173,0.18) 100%)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        px: 3,
      }}
    >
      <Stack spacing={1.25} alignItems="center" maxWidth={420}>
        <Typography variant="h6">{title}</Typography>
        <Typography variant="body2" color="text.secondary">
          {description}
        </Typography>
        {action ?? null}
      </Stack>
    </Box>
  )
}

const Surface3DView = memo(
  Surface3DViewComponent,
  (prev, next) =>
    prev.availableLabels.length === next.availableLabels.length &&
    prev.availableLabels.every((value, index) => value === next.availableLabels[index]) &&
    prev.blend === next.blend &&
    prev.errorText === next.errorText &&
    prev.hasMask === next.hasMask &&
    prev.loadHandle === next.loadHandle &&
    prev.labelColors === next.labelColors &&
    prev.crosshairPoint?.x === next.crosshairPoint?.x &&
    prev.crosshairPoint?.y === next.crosshairPoint?.y &&
    prev.crosshairPoint?.z === next.crosshairPoint?.z &&
    prev.spacing?.length === next.spacing?.length &&
    (prev.spacing ?? []).every((value, index) => value === next.spacing?.[index]) &&
    prev.volumeShape?.length === next.volumeShape?.length &&
    (prev.volumeShape ?? []).every((value, index) => value === next.volumeShape?.[index]) &&
    prev.visibleLabels.length === next.visibleLabels.length &&
    prev.visibleLabels.every((value, index) => value === next.visibleLabels[index]),
)

export default Surface3DView
