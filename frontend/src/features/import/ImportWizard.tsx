// Import wizard: a folder or one file → detected source adapters → preview (`nifti-files` options
// with a live parse) → commit + indexing job. The rules are in `model.ts` and each step renders
// itself; this component holds the state and the footer.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { api, keys, useCommitImport, useSourceDetection, useSourceOperation, useFsList, useImportPreview, useJobs, useRoots, type SourceOperation, type SourceImportUpdate, type SourceOperationStart, type ImportAdapter, type NiftiOptions, type PreviewRequest } from '../../api'
import { Dialog, openPath, ProblemCard } from '../../lib'
import { runCommand, toast } from '../../shell'
import { Icon, codicon } from '../../theme'
import { DerivedRootDialog } from './DerivedRootDialog'
import { aliasProblem, autoOptions, canNext, firstAdapter, imageStems, IMPORTABLE, initialState, jobFailed, nextAction, STEPS, type Step } from './model'
import { DetectStep } from './steps/DetectStep'
import { IndexStep } from './steps/IndexStep'
import { PreviewStep } from './steps/PreviewStep'
import { RootStep, type Uploads } from './steps/RootStep'
import { useImportWizard, type WizardPrefill } from './store'
import './import.css'

export default function Wizard({ pid, prefill }: { pid: string; prefill: WizardPrefill | null }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const close = useImportWizard((s) => s.close)
  const start = initialState(prefill)
  const [step, setStep] = useState<Step>(start.step)
  const [dir, setDir] = useState<string | null>(start.dir)
  const [file, setFile] = useState<string | null>(start.file)
  const [alias, setAlias] = useState(prefill?.alias ?? 'DATA')
  const [upload, setUpload] = useState(false)
  const [files, setFiles] = useState<Partial<Uploads>>({})
  const [adapter, setAdapter] = useState<string | null>(prefill?.adapter ?? null)
  const [options, setOptions] = useState<NiftiOptions>({ ...prefill?.options, ...(prefill?.modality ? { modality: prefill.modality } : {}) })
  const [touched, setTouched] = useState(false)
  const [reconstruct, setReconstruct] = useState(prefill?.reconstruct ?? false)
  const [anonymize, setAnonymize] = useState(prefill?.anonymize ?? false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [askDerived, setAskDerived] = useState(false)
  const detect = useSourceDetection(prefill?.discoveryId ?? null)
  const preview = useImportPreview(pid)
  const commit = useCommitImport(pid)
  const durable = useSourceOperation(prefill?.discoveryId ?? null)
  const jobs = useJobs(pid).data ?? []
  const job = durable.data?.import_job ?? jobs.find((j) => j.job_id === jobId)
  const qc = useQueryClient()
  const requests = useRef(new Map<string, string>())
  const initialized = useRef(false)
  const handoff = useMutation({
    mutationFn: (body: SourceOperationStart) => api.startSourceOperation(body),
    onSuccess: (operation) => {
      runCommand('sources.openBackground', operation.operation_id)
      close()
    },
  })
  const p = durable.data?.import_preview ?? preview.data
  const saveQueue = useRef<Promise<SourceOperation | undefined>>(Promise.resolve(undefined))
  const save = useMutation({
    mutationFn: (choices: Omit<SourceImportUpdate, 'expected_revision' | 'expected_attempt' | 'expected_run_attempt'>) => {
      const id = prefill?.discoveryId
      if (!id) throw new Error('Missing import operation')
      const prior = saveQueue.current
      const pending = prior.then(async (last) => {
        const fence = last ?? (prefill?.revision != null && prefill.attempt != null
          ? { revision: prefill.revision, attempt: prefill.attempt }
          : await api.getSourceOperation(id))
        return api.saveSourceImport(id, { ...choices, expected_revision: fence.revision, expected_attempt: fence.attempt })
      })
      saveQueue.current = pending.catch(() => prior)
      return pending
    },
    onSuccess: (operation) => qc.setQueryData(keys.sourceOperation(operation.operation_id), operation),
  })
  const work = useMutation({
    mutationFn: async ({ committing, choices }: { committing: boolean; choices: Omit<SourceImportUpdate, 'expected_revision' | 'expected_attempt' | 'expected_run_attempt'> }) => {
      const saved = await save.mutateAsync(choices)
      const fence = { expected_revision: saved.revision, expected_attempt: saved.attempt }
      return committing ? api.commitSourceImport(saved.operation_id, fence) : api.prepareSourceImport(saved.operation_id, fence)
    },
    onSuccess: (operation) => {
      qc.setQueryData(keys.sourceOperation(operation.operation_id), operation)
      runCommand('sources.openBackground', operation.operation_id)
      close()
    },
  })
  const path = file ?? dir
  const detection = detect.data?.path === path ? detect.data : undefined
  // Pattern sample: relative paths spread over the folder by detection, else the browsed folder's
  // listing, the same query as the Data root step's browser
  const listing = useFsList(dir, 'source').data
  const detected = detection?.candidates.find((c) => c.adapter === 'nifti-files')?.sample
  const fileNames = useMemo(() => (detected?.length ? detected : (listing?.entries ?? []).filter((e) => e.kind === 'file').map((e) => e.name)), [detected, listing])
  const stems = useMemo(() => imageStems(options, file, fileNames), [options, file, fileNames])
  const auto = autoOptions(adapter, touched, options, stems, file || options.include ? [] : fileNames)
  const niftiOptions = auto ? { ...options, ...auto } : options
  const choices = {
    project_id: pid, alias, adapter, add: prefill?.add ?? false,
    options: adapter === 'metadata-v1' ? (reconstruct ? { reconstruct_sidecars: true } : {}) : { ...niftiOptions },
    reconstruct, anonymize,
  }
  const serializedChoices = JSON.stringify(choices)
  const { mutate: persistDraft } = save
  useEffect(() => {
    if (!prefill?.discoveryId || !detection || step === 'root' || step === 'index') return
    const timer = setTimeout(() => persistDraft(JSON.parse(serializedChoices) as typeof choices), 500)
    return () => clearTimeout(timer)
  }, [prefill?.discoveryId, serializedChoices, persistDraft, detection, step])
  const taken = (useRoots(pid).data ?? []).find((r) => r.alias === alias)
  const aliasKind = aliasProblem(alias, taken, prefill?.add ?? false, dir)
  const aliasError = aliasKind === 'invalid' ? t('import.aliasInvalid') : aliasKind === 'taken' ? t('import.aliasTaken', { alias, path: taken?.path ?? '' }) : null
  const failed = jobFailed(job?.status)

  useEffect(() => {
    if (step === 'index' && (job?.status === 'succeeded' || (durable.data?.status === 'completed' && durable.data.import_context?.step === 'index'))) {
      void qc.invalidateQueries({ queryKey: keys.project(pid) })
      void qc.invalidateQueries({ queryKey: keys.projects() })
      const cases = p?.counts.cases
      toast({ message: cases == null ? t('import.converted') : t('import.done', { cases }), tone: 'ok' })
      if (prefill?.discoveryId) runCommand('sources.dismissBackground')
      close()
    }
  }, [job?.status, qc, close, t, p?.counts.cases, pid, prefill?.discoveryId, step, durable.data])

  const startOperation = (body: Omit<SourceOperationStart, 'idempotency_key'>) => {
    const signature = JSON.stringify(body)
    let key = requests.current.get(signature)
    if (!key) {
      key = `import-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
      requests.current.set(signature, key)
    }
    handoff.mutate({ ...body, idempotency_key: key })
  }
  const discoverSource = (target: string) => startOperation({
    path: target, project_id: pid, purpose: 'discover', prepare_plan: false,
    import_context: { alias, adapter, add: prefill?.add ?? false, options: { ...niftiOptions }, reconstruct, anonymize, step: 'detect' },
  })
  const runDetect = (target: string) => {
    setStep('detect')
    preview.reset()
    discoverSource(target)
  }
  useEffect(() => {
    if (prefill && !prefill.discoveryId) discoverSource(prefill.path)
    // once per mount; retries retain the same request key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (!detection || initialized.current) return
    initialized.current = true
    setAdapter(firstAdapter(detection.candidates, prefill?.adapter))
    setDir(detection.root)
    setFile(detection.kind === 'file' ? detection.path : null)
  }, [detection, prefill?.adapter])

  const runPreview = (a: ImportAdapter, nifti: NiftiOptions = niftiOptions) => {
    if (!path) return
    if (prefill?.discoveryId) {
      work.mutate({ committing: false, choices: { ...choices, adapter: a, options: a === 'nifti-files' ? { ...nifti } : choices.options } })
      return
    }
    const req: PreviewRequest = { root: path, alias, adapter: a, add: prefill?.add ?? false }
    if (a === 'nifti-files') req.options = nifti
    if (a === 'metadata-v1' && reconstruct) req.options = { reconstruct_sidecars: true }
    preview.mutate(req, { onSuccess: () => setStep('preview') })
  }
  // DICOM sources go through the converter task; its rows are imported on success
  const runConvert = () => {
    if (!path) return
    startOperation({
      path, project_id: pid, purpose: 'convert', prepare_plan: true,
      settings: { anonymize: anonymize ? 'basic' : 'none', target_profile: 'generic', phase_analyzer: true },
    })
  }
  const openInstead = () => {
    close()
    if (path) openPath(navigate, path)
  }

  const i = STEPS.indexOf(step)
  const enabled = canNext({ step, path, aliasOk: aliasError === null, upload, hasUploadedMetadata: files.metadata != null, adapter, previewPending: preview.isPending || handoff.isPending || work.isPending || (!upload && step === 'detect' && !detection), preview: p, commitPending: commit.isPending || work.isPending })
  const next = async () => {
    const action = nextAction(step, adapter, upload)
    if (action === 'upload-preview' && path && files.metadata) {
      setStep('detect')
      setAdapter('metadata-v1')
      preview.mutate({ root: path, alias, files: { metadata: files.metadata, phase: files.phase ?? null, voi_catalog: files.voi_catalog ?? null } }, { onSuccess: () => setStep('preview') })
    } else if (action === 'detect' && path) runDetect(path)
    else if (action === 'open') openInstead()
    else if (action === 'convert') void runConvert()
    else if (action === 'preview' && adapter) runPreview(adapter as ImportAdapter)
    else if (action === 'commit' && p) {
      if (prefill?.discoveryId) {
        work.mutate({ committing: true, choices })
        return
      }
      const r = await commit.mutateAsync(p.preview_id)
      setJobId(r.job_id)
      setStep('index')
    }
  }
  const onAction = {
    import_as: (a: string | null) => {
      if (!a) return
      setAdapter(a)
      if (IMPORTABLE.has(a)) runPreview(a as ImportAdapter)
    },
    // files that would collapse into one item; the refusal offers the folder pattern
    use_pattern: (pattern: string | null) => {
      if (!pattern) return
      const o = { ...niftiOptions, pattern }
      setTouched(true)
      setOptions(o)
      runPreview('nifti-files', o)
    },
    open: openInstead,
    choose_another_path: () => setStep('root'),
    choose_derived_root: () => setAskDerived(true),
  }

  const minimize = async () => {
    if (prefill?.discoveryId) {
      if (step !== 'index') {
        try { await save.mutateAsync(choices) } catch { return }
      }
      runCommand('sources.minimizeBackground', prefill.discoveryId)
    }
    close()
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => { if (!o) void minimize() }}
      title={t('import.title')}
      icon={codicon('folder-opened')}
      size="lg"
      footer={
        <>
          <ol className="wiz-steps" aria-label={t('import.steps')}>
            {STEPS.map((s, k) => (
              <li key={s} data-state={k < i ? 'done' : k === i ? 'current' : 'todo'}>
                <span className="wiz-dot">{k < i ? <Icon spec={codicon('check')} /> : k + 1}</span>
                {t(`import.step.${s}`)}
              </li>
            ))}
          </ol>
          <span className="grow" />
          {prefill?.discoveryId ? <button type="button" className="btn" disabled={work.isPending || save.isPending} onClick={() => void minimize()}>{t('conv.minimize')}</button> : null}
          {step === 'root' ? (
            <button type="button" className="btn" title={t('import.skipHelp')} onClick={close}>{t('import.skip')}</button>
          ) : null}
          {step !== 'root' && step !== 'index' ? (
            <button type="button" className="btn" onClick={() => setStep(STEPS[i - 1] ?? 'root')}>{t('common.back')}</button>
          ) : null}
          {step === 'index' && failed ? (
            <button type="button" className="btn" onClick={close}>{t('common.close')}</button>
          ) : null}
          {step !== 'index' ? (
            <button type="button" className="btn btn-primary" disabled={!enabled} onClick={() => void next()}>
              {step === 'preview' ? t('import.commit') : step === 'detect' && adapter === 'open' ? t('import.openInstead') : t('common.next')}
            </button>
          ) : null}
        </>
      }
    >
      {step === 'root' ? (
        <RootStep dir={dir} file={file} onDir={setDir} onFile={setFile} alias={alias} onAlias={setAlias} aliasError={aliasError} upload={upload} onUpload={setUpload} files={files} onFiles={setFiles} />
      ) : null}
      {step === 'detect' ? (
        <DetectStep
          path={path}
          pending={handoff.isPending || detect.isFetching || preview.isPending}
          errors={[detect.error, preview.error, handoff.error, save.error, work.error, durable.error]}
          onAction={onAction}
          derived={
            askDerived ? (
              <DerivedRootDialog
                pid={pid}
                onClose={(ok) => {
                  setAskDerived(false)
                  // a DICOM conversion or a sidecar reconstruction waited for the folder
                  if (ok) void (adapter === 'dicom.convert' ? runConvert() : adapter && IMPORTABLE.has(adapter) && runPreview(adapter as ImportAdapter))
                }}
              />
            ) : null
          }
          cands={detection?.candidates ?? []}
          adapter={adapter}
          onAdapter={setAdapter}
          nifti={niftiOptions}
          onNifti={(o) => {
            setTouched(true)
            setOptions(o)
          }}
          stems={stems}
          dir={file ? null : dir}
          prefilled={auto !== null}
          anonymize={anonymize}
          onAnonymize={setAnonymize}
          reconstruct={reconstruct}
          onReconstruct={setReconstruct}
          ignored={detection?.ignored}
        />
      ) : null}
      {step === 'preview' && p ? <PreviewStep p={p} /> : null}
      {step === 'index' ? <IndexStep job={job} failed={failed} /> : null}
      {step !== 'detect' && (save.error || work.error || durable.error) ? <ProblemCard error={save.error || work.error || durable.error} /> : null}
    </Dialog>
  )
}
