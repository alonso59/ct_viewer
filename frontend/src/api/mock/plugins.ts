// Mock Plugin Library (API-49): the shipped plugin.json files (hidden CI plugins left out).
// Regenerate by hand when a plugin.json changes; the mock marks every non-pending plugin ready.
import type { PluginInfo, PluginManifest } from '../types'

const MANIFESTS: PluginManifest[] = [
  {
    "plugin": 1,
    "id": "analyzers",
    "version": "1.0.0",
    "title": "Metadata analyzers",
    "description": "Phase, organ target and readiness from DICOM metadata, as annotation layers (ANALYZERS.md).",
    "icon": "symbol-property",
    "scope": "project",
    "contributes": {
      "tasks": [
        "analyzer.phase",
        "analyzer.target",
        "analyzer.readiness"
      ],
      "views": [],
      "editors": [],
      "overlays": [],
      "panels": [],
      "commands": [],
      "columns": [
        "phase",
        "target",
        "readiness"
      ],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": []
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "ccrcc",
    "version": "1.0.0",
    "title": "Study pack ccRCC",
    "description": "Kidney CT study pack: label map, phase vocabulary and mapping, organ focus for the analyzers (PRJ-16).",
    "icon": "package",
    "scope": "project",
    "contributes": {
      "tasks": [],
      "views": [],
      "editors": [],
      "overlays": [],
      "panels": [],
      "commands": [],
      "columns": [],
      "packs": [
        "ccrcc"
      ]
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": []
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "curation",
    "version": "1.0.0",
    "title": "Curation & QC",
    "description": "QC status per item and mask, correction queue, exports, v2 and converter imports, live multi-user sync (CURATION.md).",
    "icon": "checklist",
    "scope": "project",
    "contributes": {
      "tasks": [],
      "views": [
        "curation",
        "history"
      ],
      "editors": [
        "queue"
      ],
      "overlays": [],
      "panels": [
        "history"
      ],
      "commands": [
        "curation.openQueue",
        "curation.writeExports"
      ],
      "columns": [],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": [
        "event_store"
      ]
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "dashboard",
    "version": "1.0.0",
    "title": "Dashboard & analysis",
    "description": "Feature QC views, click-through to the viewer and guided statistics on any features run (DASHBOARD.md, ANALYSIS.md).",
    "icon": "graph",
    "scope": "project",
    "contributes": {
      "tasks": [],
      "views": [
        "dashboards"
      ],
      "editors": [
        "run"
      ],
      "overlays": [],
      "panels": [
        "measurements"
      ],
      "commands": [],
      "columns": [],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [
        "radiomics"
      ],
      "capabilities": [
        "features_run"
      ]
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "dicom",
    "version": "1.0.0",
    "title": "DICOM converter",
    "description": "Converts a DICOM folder or file to NIfTI with JSON sidecars and a metadata.jsonl artifact (DICOM_CONVERTER.md).",
    "icon": "file-binary",
    "scope": "workspace",
    "contributes": {
      "tasks": [
        "dicom.convert"
      ],
      "views": [],
      "editors": [],
      "overlays": [],
      "panels": [],
      "commands": [
        "tasks.convertDicom"
      ],
      "columns": [],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": [
        "derived_root"
      ]
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "generic-ct",
    "version": "1.0.0",
    "title": "Study pack Generic CT",
    "description": "Generic CT phase vocabulary and mapping (PRJ-16).",
    "icon": "package",
    "scope": "project",
    "contributes": {
      "tasks": [],
      "views": [],
      "editors": [],
      "overlays": [],
      "panels": [],
      "commands": [],
      "columns": [],
      "packs": [
        "generic-ct"
      ]
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": []
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "labeling",
    "version": "1.0.0",
    "title": "Labeling table",
    "description": "User-defined label tables at patient, CT or item level with typed columns, spreadsheet editing, live multi-user sync; every column is a layer and a study variable (LABELING.md).",
    "icon": "table",
    "scope": "project",
    "contributes": {
      "tasks": [],
      "views": [
        "labeling"
      ],
      "editors": [
        "labeling"
      ],
      "overlays": [],
      "panels": [],
      "commands": [
        "labeling.newTable"
      ],
      "columns": [
        "lbl.*"
      ],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": [
        "event_store"
      ]
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "nnunet",
    "version": "0.0.0",
    "title": "nnU-Net segmentation",
    "description": "Segmentation with a trained nnU-Net model on a GPU host through the external runner; outputs a segmentation set.",
    "icon": "layers",
    "scope": "project",
    "contributes": {
      "tasks": [
        "segment.nnunet"
      ],
      "views": [],
      "editors": [],
      "overlays": [],
      "panels": [],
      "commands": [],
      "columns": [],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": [
        "runner"
      ]
    },
    "pending": true,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "radiomics",
    "version": "1.0.0",
    "title": "Radiomics",
    "description": "PyRadiomics features on a segmentation set with profiles, estimate and resumable runs (RADIOMICS.md).",
    "icon": "beaker",
    "scope": "project",
    "contributes": {
      "tasks": [
        "radiomics.pyradiomics"
      ],
      "views": [
        "radiomics"
      ],
      "editors": [
        "radiomics"
      ],
      "overlays": [],
      "panels": [],
      "commands": [
        "radiomics.new"
      ],
      "columns": [],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": [
        "segmentation"
      ]
    },
    "pending": false,
    "hidden": false
  },
  {
    "plugin": 1,
    "id": "voi",
    "version": "0.0.0",
    "title": "VOI extractor",
    "description": "Crops VOIs (image + mask, per side) from a segmentation set with the target labels.",
    "icon": "screen-full",
    "scope": "project",
    "contributes": {
      "tasks": [
        "voi.extract"
      ],
      "views": [],
      "editors": [],
      "overlays": [],
      "panels": [],
      "commands": [],
      "columns": [],
      "packs": []
    },
    "requires": {
      "core": ">=3.0",
      "plugins": [],
      "capabilities": [
        "segmentation"
      ]
    },
    "pending": true,
    "hidden": false
  }
]

export const MOCK_PLUGINS: PluginInfo[] = MANIFESTS.map((manifest) =>
  manifest.pending
    ? { manifest, status: 'pending', reason: 'Not available yet: planned for a later release.', actions: [] }
    : { manifest, status: 'ready', reason: null, actions: [] },
)
