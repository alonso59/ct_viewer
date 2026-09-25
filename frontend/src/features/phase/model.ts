// Native phase selection helpers (PHASE.md, ADR-0026): pure, unit-tested.
import { PHASES, type ItemRecord } from '../../api'

/** PHS-01 buttons: the project's phase vocabulary; an open vocabulary falls back to the defaults */
export function phaseOptions(vocabulary: string[] | undefined): string[] {
  return vocabulary?.length ? vocabulary : PHASES
}

/** PHS-04: the run whose guess is the scan's effective phase, when it is the active
 *  `analyzer.phase` run (INPUT_METADATA §Phase resolution names it `analyzer:{run_id}`) */
export function guessRun(phase: Pick<ItemRecord['phase'], 'source'>, activeRun: string | null | undefined): string | null {
  const m = /^analyzer:(.+)$/.exec(phase.source)
  return m?.[1] && m[1] === activeRun ? m[1] : null
}
