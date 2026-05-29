import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Alert, Box, Button, CircularProgress, Stack, Typography } from '@mui/material'
import { Bounds, OrbitControls, useBounds } from '@react-three/drei'
import { Canvas, useThree } from '@react-three/fiber'
import axios from 'axios'
import {
  Group,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PerspectiveCamera,
  type Material,
} from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'

import { apiClient, getApiErrorMessage, isHandleExpiredError } from '../../services/api'

interface Surface3DViewProps {
  blend: number
  errorText?: string | null
  hasMask: boolean
  labelColors: Record<number, string>
  loadHandle: string | null
  onHandleExpired?: () => void
  visibleLabels: number[]
}

interface MeshEntry {
  label: number
  object: Object3D
}

type CameraPreset = 'front' | 'side' | 'top'

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

function applyVisualStyle(root: Object3D, color: string, blend: number): void {
  root.traverse((node) => {
    if (!isMeshObject(node)) {
      return
    }

    toMaterialList(node.material).forEach((material) => material.dispose())
    node.material = new MeshStandardMaterial({
      color,
      opacity: blend,
      transparent: blend < 1,
      roughness: 0.52,
      metalness: 0.02,
      emissive: color,
      emissiveIntensity: 0.05,
    })
    node.castShadow = false
    node.receiveShadow = true
  })
}

function updateBlend(root: Object3D, blend: number): void {
  root.traverse((node) => {
    if (!isMeshObject(node)) {
      return
    }
    toMaterialList(node.material).forEach((material) => {
      if (material instanceof MeshStandardMaterial) {
        material.opacity = blend
        material.transparent = blend < 1
        material.needsUpdate = true
      }
    })
  })
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
  blend,
  errorText,
  hasMask,
  labelColors,
  loadHandle,
  onHandleExpired,
  visibleLabels,
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
  const [cameraPreset, setCameraPreset] = useState<CameraPreset>('front')
  const [fitTick, setFitTick] = useState(0)
  const [presetTick, setPresetTick] = useState(0)
  const [surface3dEnabled, setSurface3dEnabled] = useState(true)
  const inFlightRef = useRef(new Map<number, AbortController>())
  const meshesRef = useRef<Record<number, MeshEntry>>({})

  const sortedVisibleLabels = useMemo(
    () => [...visibleLabels].sort((left, right) => left - right),
    [visibleLabels],
  )
  const seriesKey = loadHandle && hasMask ? loadHandle : null

  useEffect(() => {
    meshesRef.current = requestState.meshesByLabel
  }, [requestState.meshesByLabel])

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
    if (!seriesKey || sortedVisibleLabels.length === 0 || !surface3dEnabled) {
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
      const color = labelColors[label] ?? '#f5f5f5'

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
            setPresetTick((current) => current + 1)
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
    onHandleExpired,
    requestState.failedLabels,
    requestState.loadingLabels,
    requestState.meshesByLabel,
    seriesKey,
    sortedVisibleLabels,
    surface3dEnabled,
  ])

  useEffect(() => {
    Object.values(requestState.meshesByLabel).forEach((entry) => updateBlend(entry.object, blend))
  }, [blend, requestState.meshesByLabel])

  useEffect(() => {
    return () => {
      inFlightRef.current.forEach((controller) => controller.abort())
      inFlightRef.current.clear()
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
      data-surface-loading={isLoading ? 'true' : 'false'}
      sx={{
        position: 'relative',
        flex: 1,
        minHeight: 0,
        minWidth: 0,
        borderRadius: 3,
        overflow: 'hidden',
        border: '1px solid',
        borderColor: 'divider',
        background:
          'radial-gradient(circle at top, rgba(125, 211, 252, 0.08), transparent 22%), #040608',
      }}
    >
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={1}
        justifyContent="space-between"
        sx={{
          position: 'absolute',
          top: 12,
          left: 12,
          right: 12,
          zIndex: 2,
          pointerEvents: 'none',
        }}
      >
        <Stack spacing={0.35}>
          <Typography variant="caption" sx={{ color: 'rgba(221,221,221,0.92)' }}>
            Drag to rotate, scroll to zoom, Shift-drag to pan
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Visible structures: {sortedVisibleLabels.join(', ')}
          </Typography>
        </Stack>
        <Stack direction="row" spacing={0.75} sx={{ pointerEvents: 'auto', flexWrap: 'wrap' }}>
          <PanelChip
            active={cameraPreset === 'front'}
            label="Front"
            onClick={() => {
              setCameraPreset('front')
              setPresetTick((current) => current + 1)
            }}
          />
          <PanelChip
            active={cameraPreset === 'side'}
            label="Side"
            onClick={() => {
              setCameraPreset('side')
              setPresetTick((current) => current + 1)
            }}
          />
          <PanelChip
            active={cameraPreset === 'top'}
            label="Top"
            onClick={() => {
              setCameraPreset('top')
              setPresetTick((current) => current + 1)
            }}
          />
          <Button
            size="small"
            variant="outlined"
            onClick={() => {
              setFitTick((current) => current + 1)
              setPresetTick((current) => current + 1)
            }}
            sx={{
              minWidth: 0,
              px: 1.2,
              color: 'text.secondary',
              borderColor: 'rgba(255,255,255,0.16)',
              backgroundColor: 'rgba(8, 12, 16, 0.72)',
            }}
          >
            Reset view
          </Button>
          {requestState.failedLabels.size > 0 ? (
            <Button
              size="small"
              variant="outlined"
              color="warning"
              onClick={() => {
                setRequestState((current) => ({
                  ...current,
                  error: null,
                  failedLabels: new Set(),
                }))
              }}
              sx={{
                minWidth: 0,
                px: 1.2,
                backgroundColor: 'rgba(8, 12, 16, 0.72)',
              }}
            >
              Retry
            </Button>
          ) : null}
          <Button
            size="small"
            variant="outlined"
            color="error"
            onClick={() => setSurface3dEnabled(false)}
            sx={{
              minWidth: 0,
              px: 1.2,
              borderColor: 'rgba(255,100,100,0.3)',
              backgroundColor: 'rgba(8, 12, 16, 0.72)',
            }}
          >
            Disable 3D
          </Button>
        </Stack>
      </Stack>

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
        >
          <SurfaceScene
            cameraPreset={cameraPreset}
            fitTick={fitTick}
            meshes={renderedMeshes}
            presetTick={presetTick}
          />
        </Canvas>
      )}

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
            backgroundColor: 'rgba(0, 0, 0, 0.2)',
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
  cameraPreset,
  fitTick,
  meshes,
  presetTick,
}: {
  cameraPreset: CameraPreset
  fitTick: number
  meshes: MeshEntry[]
  presetTick: number
}) {
  const controlsRef = useRef<OrbitControlsImpl | null>(null)
  const groupRef = useRef<Group | null>(null)

  return (
    <>
      <color attach="background" args={['#040608']} />
      <fog attach="fog" args={['#040608', 560, 2100]} />
      <ambientLight intensity={0.5} />
      <hemisphereLight args={['#dbeafe', '#0b1018', 1.2]} />
      <directionalLight position={[260, 360, 180]} intensity={1.45} />
      <directionalLight position={[-180, 140, -220]} intensity={0.35} color="#cbd5e1" />
      <Bounds fit clip margin={1.1}>
        <group ref={groupRef}>
          {meshes.map((entry) => (
            <primitive key={entry.label} object={entry.object} />
          ))}
        </group>
        <SceneCameraController
          cameraPreset={cameraPreset}
          controlsRef={controlsRef}
          fitTick={fitTick}
          meshCount={meshes.length}
          presetTick={presetTick}
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
  cameraPreset,
  controlsRef,
  fitTick,
  meshCount,
  presetTick,
  targetRef,
}: {
  cameraPreset: CameraPreset
  controlsRef: React.RefObject<OrbitControlsImpl | null>
  fitTick: number
  meshCount: number
  presetTick: number
  targetRef: React.RefObject<Group | null>
}) {
  const bounds = useBounds()
  const { camera } = useThree()

  useEffect(() => {
    if (!targetRef.current || meshCount === 0) {
      return
    }
    bounds.refresh(targetRef.current).clip().fit()
  }, [bounds, fitTick, meshCount, targetRef])

  useEffect(() => {
    if (meshCount === 0 || !(camera instanceof PerspectiveCamera)) {
      return
    }
    const distance = camera.position.length() || 320
    const target = controlsRef.current?.target
    const targetX = target?.x ?? 0
    const targetY = target?.y ?? 0
    const targetZ = target?.z ?? 0

    if (cameraPreset === 'front') {
      camera.position.set(targetX + distance * 0.8, targetY + distance * 0.45, targetZ + distance * 0.8)
    } else if (cameraPreset === 'side') {
      camera.position.set(targetX + distance * 1.15, targetY + distance * 0.18, targetZ)
    } else {
      camera.position.set(targetX, targetY + distance * 1.2, targetZ + distance * 0.08)
    }
    camera.lookAt(targetX, targetY, targetZ)
    camera.updateProjectionMatrix()
    controlsRef.current?.update()
  }, [camera, cameraPreset, controlsRef, meshCount, presetTick])

  return null
}

function PanelChip({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <Button
      size="small"
      variant={active ? 'contained' : 'outlined'}
      onClick={onClick}
      sx={{
        minWidth: 0,
        px: 1.2,
        color: active ? '#041018' : 'text.secondary',
        borderColor: active ? 'transparent' : 'rgba(255,255,255,0.16)',
        backgroundColor: active ? '#7dd3fc' : 'rgba(8, 12, 16, 0.72)',
        '&:hover': {
          backgroundColor: active ? '#93ddff' : 'rgba(18, 28, 36, 0.88)',
        },
      }}
    >
      {label}
    </Button>
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
        borderColor: 'divider',
        background:
          'radial-gradient(circle at top, rgba(125, 211, 252, 0.08), transparent 42%), rgba(255,255,255,0.015)',
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
    prev.blend === next.blend &&
    prev.errorText === next.errorText &&
    prev.hasMask === next.hasMask &&
    prev.loadHandle === next.loadHandle &&
    prev.labelColors === next.labelColors &&
    prev.visibleLabels.length === next.visibleLabels.length &&
    prev.visibleLabels.every((value, index) => value === next.visibleLabels[index]),
)

export default Surface3DView
