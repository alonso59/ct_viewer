// Radiomics wire types (API-30..37), taken from the generated OpenAPI schema (FE-03).
import type { components } from '../../../api/schema'

type S = components['schemas']

export type SettingsSchema = S['SettingsSchema']
export type OptionSpec = S['OptionSpec']
export type FilterSpec = S['FilterSpec']
export type FeatureClassSpec = S['FeatureClassSpec']
export type WireSettings = S['RadiomicsSettings']
export type ServerIssue = S['Issue']
export type ValidateResult = S['ValidateResult']
export type Selection = S['Selection']
export type SelectionFilter = S['SelectionFilter']
export type EstimateResult = S['EstimateResult']
export type Profile = S['app__radiomics__models__Profile']
export type RunSummary = S['RunSummary']
export type RunDetail = S['RunDetail']
export type RunStatus = RunSummary['status']
export type RunError = S['Page_RunError_']['items'][number]

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
