import type { SourceOperation } from '../../api'
import { showOutput } from '../../features/jobs'
import i18n from '../../i18n'

/** Follow an operation's server log in the Output tab: its workspace conversion once one runs
 *  (a project conversion is a project run, so the operation's own log stays shown), else the
 *  operation itself */
export function showOperationOutput(operation: SourceOperation) {
  const run = operation.project_id ? null : operation.conversion_run
  showOutput({
    id: `dicom.${operation.operation_id}`,
    label: i18n.t('output.operation', { name: operation.dataset_name ?? 'DICOM' }),
    ...(run ? { kind: 'workspace-run', ref: run.run_id } : { kind: 'source-operation', ref: operation.operation_id }),
  })
}
