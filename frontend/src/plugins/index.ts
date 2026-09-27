// First-party plugins shipped with the app (PLG-01). Pending plugins (nnU-Net, VOI extractor) have
// no UI yet: the Library lists them from API-49 without an Open action (PLG-09).
import { plugin as analyzers } from './analyzers'
import { plugin as curation } from './curation'
import { plugin as dashboard } from './dashboard'
import { plugin as dicom } from './dicom'
import { plugin as labeling } from './labeling'
import { packs } from './packs'
import type { FrontendPlugin } from './host'
import { plugin as radiomics } from './radiomics'

export const FIRST_PARTY: FrontendPlugin[] = [dicom, analyzers, curation, labeling, radiomics, dashboard, ...packs]
export { activatePlugins, isActive, openerOf, type FrontendPlugin } from './host'
export { useCurationRuntime } from './curation'
