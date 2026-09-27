// Radiomics wire types (API-30..37) from the shared API layer, under the names this feature uses.
export type {
  EstimateResult,
  FeatureClassSpec,
  FilterSpec,
  OptionSpec,
  Profile,
  RunStatus,
  RunSummary,
  Selection,
  SelectionFilter,
  SettingsSchema,
  RadiomicsSettings as WireSettings,
  ValidationIssue as ServerIssue,
} from '../../../api/types'

/** A form value: every option type the schema declares (bool, int, float, str, enum, lists) */
export type Value = boolean | number | string | number[] | null

/** Editable form state; converted to and from `RadiomicsSettings` by `model/settings.ts` */
export interface FormState {
  /** Image types (filters): on/off plus that filter's parameters */
  filters: Record<string, { enabled: boolean; params: Record<string, Value> }>
  /** Selected features per class; a class is on when it has at least one feature (RAD-02) */
  features: Record<string, string[]>
  /** Top-level engine settings by name */
  options: Record<string, Value>
}

/** One validation finding. `loc` uses the server's paths (API-31) so both sources merge per field. */
export interface Issue {
  loc: (string | number)[]
  rule: string
  severity: 'error' | 'warning'
  /** i18n key under `rad.rule.*` for client issues; absent for server issues (use `msg`) */
  key?: string
  params?: Record<string, string | number>
  msg?: string
}
