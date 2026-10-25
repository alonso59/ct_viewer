import { PHASES, type ItemRecord } from '../../api'

/** The project's phase vocabulary; an open vocabulary falls back to the defaults */
export function phaseOptions(vocabulary: string[] | undefined): string[] {
  return vocabulary?.length ? vocabulary : PHASES
}

/** The run whose guess is the scan's effective phase, when it is the active `analyzer.phase` run
 *  (phase source `analyzer:{run_id}`) */
export function guessRun(phase: Pick<ItemRecord['phase'], 'source'>, activeRun: string | null | undefined): string | null {
  const m = /^analyzer:(.+)$/.exec(phase.source)
  return m?.[1] && m[1] === activeRun ? m[1] : null
}
