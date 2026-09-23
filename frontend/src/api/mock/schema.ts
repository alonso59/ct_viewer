// Mock of GET /radiomics/schema (API-30), following RADIOMICS §Settings groups.
// The real list comes from the engine at runtime; nothing here is hard-coded in the form.
import type { Issue, Settings, SettingsSchema } from '../types'

const FEATURES: Record<string, string[]> = {
  firstorder: [
    'Energy', 'TotalEnergy', 'Entropy', 'Minimum', '10Percentile', '90Percentile', 'Maximum',
    'Mean', 'Median', 'InterquartileRange', 'Range', 'MeanAbsoluteDeviation',
    'RobustMeanAbsoluteDeviation', 'RootMeanSquared', 'StandardDeviation', 'Skewness',
    'Kurtosis', 'Variance', 'Uniformity',
  ],
  shape: [
    'MeshVolume', 'VoxelVolume', 'SurfaceArea', 'SurfaceVolumeRatio', 'Sphericity',
    'Maximum3DDiameter', 'Maximum2DDiameterSlice', 'Maximum2DDiameterColumn',
    'Maximum2DDiameterRow', 'MajorAxisLength', 'MinorAxisLength', 'LeastAxisLength',
    'Elongation', 'Flatness',
  ],
  shape2D: [
    'MeshSurface', 'PixelSurface', 'Perimeter', 'PerimeterSurfaceRatio', 'Sphericity',
    'MaximumDiameter', 'MajorAxisLength', 'MinorAxisLength', 'Elongation',
  ],
  glcm: [
    'Autocorrelation', 'JointAverage', 'ClusterProminence', 'ClusterShade', 'ClusterTendency',
    'Contrast', 'Correlation', 'DifferenceAverage', 'DifferenceEntropy', 'DifferenceVariance',
    'JointEnergy', 'JointEntropy', 'Imc1', 'Imc2', 'Idm', 'Idmn', 'Id', 'Idn',
    'InverseVariance', 'MaximumProbability', 'SumEntropy', 'SumSquares', 'MCC',
  ],
  glrlm: [
    'ShortRunEmphasis', 'LongRunEmphasis', 'GrayLevelNonUniformity',
    'GrayLevelNonUniformityNormalized', 'RunLengthNonUniformity',
    'RunLengthNonUniformityNormalized', 'RunPercentage', 'GrayLevelVariance', 'RunVariance',
    'RunEntropy', 'LowGrayLevelRunEmphasis', 'HighGrayLevelRunEmphasis',
    'ShortRunLowGrayLevelEmphasis', 'ShortRunHighGrayLevelEmphasis',
    'LongRunLowGrayLevelEmphasis', 'LongRunHighGrayLevelEmphasis',
  ],
  glszm: [
    'SmallAreaEmphasis', 'LargeAreaEmphasis', 'GrayLevelNonUniformity',
    'GrayLevelNonUniformityNormalized', 'SizeZoneNonUniformity',
    'SizeZoneNonUniformityNormalized', 'ZonePercentage', 'GrayLevelVariance', 'ZoneVariance',
    'ZoneEntropy', 'LowGrayLevelZoneEmphasis', 'HighGrayLevelZoneEmphasis',
    'SmallAreaLowGrayLevelEmphasis', 'SmallAreaHighGrayLevelEmphasis',
    'LargeAreaLowGrayLevelEmphasis', 'LargeAreaHighGrayLevelEmphasis',
  ],
  gldm: [
    'SmallDependenceEmphasis', 'LargeDependenceEmphasis', 'GrayLevelNonUniformity',
    'DependenceNonUniformity', 'DependenceNonUniformityNormalized', 'GrayLevelVariance',
    'DependenceVariance', 'DependenceEntropy', 'LowGrayLevelEmphasis', 'HighGrayLevelEmphasis',
    'SmallDependenceLowGrayLevelEmphasis', 'SmallDependenceHighGrayLevelEmphasis',
    'LargeDependenceLowGrayLevelEmphasis', 'LargeDependenceHighGrayLevelEmphasis',
  ],
  ngtdm: ['Coarseness', 'Contrast', 'Busyness', 'Complexity', 'Strength'],
}

export const MOCK_SCHEMA: SettingsSchema = {
  engine: { name: 'pyradiomics', version: '3.x (mock)' },
  groups: [
    {
      id: 'filters',
      title: 'Filters (image types)',
      options: [
        { key: 'imageType.Original', title: 'Original', type: 'bool', default: true },
        { key: 'imageType.LoG', title: 'Laplacian of Gaussian', type: 'bool', default: false },
        { key: 'sigma', title: 'Sigma (mm)', type: 'float_list', default: [], parent: 'imageType.LoG', help: 'One LoG image per sigma' },
        { key: 'imageType.Wavelet', title: 'Wavelet', type: 'bool', default: false },
        { key: 'wavelet', title: 'Wavelet', type: 'select', default: 'coif1', choices: ['haar', 'db1', 'db2', 'coif1', 'sym2', 'bior1.1'], parent: 'imageType.Wavelet' },
        { key: 'start_level', title: 'Start level', type: 'int', default: 0, min: 0, parent: 'imageType.Wavelet' },
        { key: 'level', title: 'Levels', type: 'int', default: 1, min: 1, parent: 'imageType.Wavelet' },
        { key: 'imageType.Square', title: 'Square', type: 'bool', default: false },
        { key: 'imageType.SquareRoot', title: 'Square root', type: 'bool', default: false },
        { key: 'imageType.Logarithm', title: 'Logarithm', type: 'bool', default: false },
        { key: 'imageType.Exponential', title: 'Exponential', type: 'bool', default: false },
        { key: 'imageType.Gradient', title: 'Gradient', type: 'bool', default: false },
        { key: 'gradientUseSpacing', title: 'Use spacing', type: 'bool', default: true, parent: 'imageType.Gradient' },
        { key: 'imageType.LBP2D', title: 'Local binary pattern (2D)', type: 'bool', default: false },
        { key: 'lbp2DRadius', title: 'Radius (mm)', type: 'float', default: 1, min: 0, parent: 'imageType.LBP2D' },
        { key: 'lbp2DSamples', title: 'Samples', type: 'int', default: 9, min: 1, parent: 'imageType.LBP2D' },
        { key: 'lbp2DMethod', title: 'Method', type: 'select', default: 'uniform', choices: ['default', 'ror', 'uniform', 'var'], parent: 'imageType.LBP2D' },
        { key: 'imageType.LBP3D', title: 'Local binary pattern (3D)', type: 'bool', default: false },
        { key: 'lbp3DLevels', title: 'Levels', type: 'int', default: 2, min: 1, parent: 'imageType.LBP3D' },
        { key: 'lbp3DIcosphereRadius', title: 'Icosphere radius (mm)', type: 'float', default: 1, min: 0, parent: 'imageType.LBP3D' },
        { key: 'lbp3DIcosphereSubdivision', title: 'Icosphere subdivision', type: 'int', default: 1, min: 0, parent: 'imageType.LBP3D' },
      ],
    },
    {
      id: 'features',
      title: 'Feature classes',
      options: Object.keys(FEATURES).map((c) => ({
        key: `featureClass.${c}`,
        title: c,
        type: 'bool' as const,
        default: c !== 'shape2D',
      })),
      features: FEATURES,
    },
    {
      id: 'discretization',
      title: 'Discretization',
      options: [
        { key: 'binWidth', title: 'Bin width', type: 'float', default: 25, min: 0, nullable: true, help: 'Use either bin width or bin count' },
        { key: 'binCount', title: 'Bin count', type: 'int', default: null, min: 1, nullable: true },
      ],
    },
    {
      id: 'resampling',
      title: 'Resampling',
      options: [
        { key: 'resampledPixelSpacing', title: 'Pixel spacing [x, y, z] mm', type: 'float_list', default: null, nullable: true, help: '0 keeps the original spacing for that axis' },
        { key: 'interpolator', title: 'Interpolator', type: 'select', default: 'sitkBSpline', choices: ['sitkNearestNeighbor', 'sitkLinear', 'sitkBSpline', 'sitkGaussian', 'sitkLanczosWindowedSinc'] },
        { key: 'padDistance', title: 'Pad distance (voxels)', type: 'int', default: 5, min: 0 },
        { key: 'preCrop', title: 'Pre-crop', type: 'bool', default: false },
      ],
    },
    {
      id: 'intensity',
      title: 'Intensity',
      options: [
        { key: 'normalize', title: 'Normalize', type: 'bool', default: false },
        { key: 'normalizeScale', title: 'Normalize scale', type: 'float', default: 1, min: 0, parent: 'normalize' },
        { key: 'removeOutliers', title: 'Remove outliers (σ)', type: 'float', default: null, nullable: true, min: 0, parent: 'normalize' },
        { key: 'voxelArrayShift', title: 'Voxel array shift', type: 'float', default: 0 },
      ],
    },
    {
      id: 'resegmentation',
      title: 'Re-segmentation',
      options: [
        { key: 'resegmentRange', title: 'Range [min, max]', type: 'float_list', default: null, nullable: true },
        { key: 'resegmentMode', title: 'Mode', type: 'select', default: 'absolute', choices: ['absolute', 'relative', 'sigma'] },
        { key: 'resegmentShape', title: 'Apply to shape', type: 'bool', default: false },
      ],
    },
    {
      id: 'mask',
      title: 'Mask handling',
      options: [
        { key: 'minimumROIDimensions', title: 'Minimum ROI dimensions', type: 'int', default: 2, min: 1, max: 3 },
        { key: 'minimumROISize', title: 'Minimum ROI size (voxels)', type: 'int', default: null, nullable: true, min: 1 },
        { key: 'geometryTolerance', title: 'Geometry tolerance', type: 'float', default: null, nullable: true, min: 0 },
        { key: 'correctMask', title: 'Correct mask', type: 'bool', default: false },
      ],
    },
    {
      id: 'twod',
      title: '2D',
      options: [
        { key: 'force2D', title: 'Force 2D', type: 'bool', default: false },
        { key: 'force2Ddimension', title: '2D dimension', type: 'int', default: 0, min: 0, max: 2, parent: 'force2D' },
      ],
    },
    {
      id: 'texture',
      title: 'Texture',
      options: [
        { key: 'distances', title: 'Distances', type: 'int_list', default: [1] },
        { key: 'symmetricalGLCM', title: 'Symmetrical GLCM', type: 'bool', default: true },
        { key: 'weightingNorm', title: 'Weighting norm', type: 'select', default: 'none', choices: ['none', 'manhattan', 'euclidean', 'infinity', 'no_weighting'] },
        { key: 'gldm_a', title: 'GLDM alpha', type: 'int', default: 0, min: 0 },
      ],
    },
    {
      id: 'output',
      title: 'Output',
      options: [{ key: 'additionalInfo', title: 'Diagnostics (additional info)', type: 'bool', default: true }],
    },
  ],
}

export function defaultSettings(schema: SettingsSchema = MOCK_SCHEMA): Settings {
  const s: Settings = {}
  for (const g of schema.groups) {
    for (const o of g.options) s[o.key] = o.default
    if (g.features) for (const [cls, list] of Object.entries(g.features)) s[`features.${cls}`] = [...list]
  }
  return s
}

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const list = (v: unknown): number[] => (Array.isArray(v) ? v.filter((x): x is number => typeof x === 'number') : [])

// RADIOMICS §Validation rules. The mock server and the live form share this function.
export function validateSettings(s: Settings, selection: { labels: number[]; items: number }): Issue[] {
  const issues: Issue[] = []
  const err = (field: string | null, message: string) => issues.push({ field, severity: 'error', message })
  const bw = num(s.binWidth)
  const bc = num(s.binCount)
  if ((bw === null) === (bc === null)) err('binWidth', 'Choose bin width or bin count')
  if (s['imageType.LoG'] === true && !list(s.sigma).some((x) => x > 0)) err('sigma', 'LoG needs at least one sigma')
  if ((s['featureClass.shape2D'] === true || s['imageType.LBP2D'] === true) && s.force2D !== true)
    err('force2D', 'Enable 2D mode for this option')
  const sp = s.resampledPixelSpacing
  if (sp !== null && sp !== undefined && (list(sp).length !== 3 || list(sp).some((x) => x < 0)))
    err('resampledPixelSpacing', 'Spacing must be positive')
  const rr = s.resegmentRange
  if (rr !== null && rr !== undefined) {
    const r = list(rr)
    if (s.resegmentMode === 'sigma') {
      if (r.length !== 1 || (r[0] ?? 0) <= 0) err('resegmentRange', 'Sigma mode needs one positive value')
    } else if (r.length !== 2 || (r[0] ?? 0) >= (r[1] ?? 0)) err('resegmentRange', 'Minimum must be below maximum')
  }
  const anyFilter = Object.keys(s).some((k) => k.startsWith('imageType.') && s[k] === true)
  const anyFeature = Object.keys(s).some((k) => {
    if (!k.startsWith('featureClass.') || s[k] !== true) return false
    const picked = s[`features.${k.slice('featureClass.'.length)}`]
    return Array.isArray(picked) && picked.length > 0
  })
  if (!anyFilter || !anyFeature || selection.labels.length === 0 || selection.items === 0)
    err(null, 'Nothing to extract')
  if (s.normalize === true && s.resegmentMode === 'absolute' && rr)
    issues.push({ field: 'normalize', severity: 'warning', message: 'HU range will be applied after normalization' })
  return issues
}
