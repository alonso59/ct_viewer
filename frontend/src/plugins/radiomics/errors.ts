// problem+json `detail`/`title` for toasts and error states (FE-09)
import { ProblemError } from '../../api'

export const errorMessage = (e: unknown, fallback: string): string => (e instanceof ProblemError ? (e.detail ?? e.title) : fallback)
