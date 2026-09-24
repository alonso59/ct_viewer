// Dashboard sub-panels (DB-01): one per DASHBOARD §Views entry, plus the Analysis panel (DB-08)
import type { ComponentType } from 'react'

import type { DashboardView } from '../../../api'
import { AnalysisPanel } from '../AnalysisPanel'
import { AssociationView } from './Association'
import { BalanceView } from './Balance'
import type { ViewProps } from './common'
import { ConsistencyView } from './Consistency'
import { CorrelationView } from './Correlation'
import { DistributionView } from './Distribution'
import { EmbeddingView } from './Embedding'
import { FeatureVsVolumeView } from './FeatureVsVolume'
import { GroupComparisonView } from './GroupComparison'
import { MissingMatrixView } from './MissingMatrix'
import { OutliersView } from './Outliers'
import { RunOverviewView } from './RunOverview'

export type PanelId = DashboardView | 'analysis'

export interface PanelDef {
  id: PanelId
  component: ComponentType<ViewProps>
}

/** Order = default arrangement and the "Views" menu */
export const PANELS: PanelDef[] = [
  { id: 'run-overview', component: RunOverviewView },
  { id: 'outliers', component: OutliersView },
  { id: 'feature-distribution', component: DistributionView },
  { id: 'embedding', component: EmbeddingView },
  { id: 'feature-vs-volume', component: FeatureVsVolumeView },
  { id: 'correlation', component: CorrelationView },
  { id: 'missing-matrix', component: MissingMatrixView },
  { id: 'phase-side-consistency', component: ConsistencyView },
  { id: 'group-comparison', component: GroupComparisonView },
  { id: 'association', component: AssociationView },
  { id: 'balance', component: BalanceView },
  { id: 'analysis', component: AnalysisPanel },
]

export { ItemMenu } from './common'
