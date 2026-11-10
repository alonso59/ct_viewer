// First-party plugins shipped with the app.
import { plugin as analyzers } from './analyzers'
import { plugin as curation } from './curation'
import { plugin as dashboard } from './dashboard'
import { plugin as dicom } from './dicom'
import { plugin as labeling } from './labeling'
import { packs } from './packs'
import type { FrontendPlugin } from './host'
import { plugin as nnunet } from './nnunet'
import { plugin as radiomics } from './radiomics'
import { plugin as voi } from './voi'

export const FIRST_PARTY: FrontendPlugin[] = [dicom, analyzers, curation, labeling, radiomics, dashboard, nnunet, voi, ...packs]
export { activatePlugins, isActive, openerOf, type FrontendPlugin } from './host'
export { useCurationRuntime } from './curation'
