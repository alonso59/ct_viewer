// Import wizard: a folder or one file → detected source adapters → preview (`nifti-files` options
// with a live parse) → commit + indexing job. The rules are in `model.ts` and each step renders
// itself; this component holds the state and the footer.
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { api, keys, useCommitImport, useDetect, useFsList, useImportPreview, useJobs, useRoots, type DetectCandidate, type ImportAdapter, type NiftiOptions, type PreviewRequest } from '../../api'
import { Dialog, openPath } from '../../lib'
import { toast } from '../../shell'
import { useReviewer } from '../../state'
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
  const [alias, setAlias] = useState('DATA')
  const [upload, setUpload] = useState(false)
  const [files, setFiles] = useState<Partial<Uploads>>({})
  const [adapter, setAdapter] = useState<string | null>(prefill?.adapter ?? null)
  const [options, setOptions] = useState<NiftiOptions>({ ...prefill?.options, ...(prefill?.modality ? { modality: prefill.modality } : {}) })
  const [touched, setTouched] = useState(false)
  const [reconstruct, setReconstruct] = useState(false)
  const [anonymize, setAnonymize] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [convertError, setConvertError] = useState<unknown>(null)
  const [askDerived, setAskDerived] = useState(false)
  const reviewer = useReviewer((s) => s.name)
  const detect = useDetect()
  const preview = useImportPreview(pid)
  const commit = useCommitImport(pid)
  const job = (useJobs(pid).data ?? []).find((j) => j.job_id === jobId)
  const qc = useQueryClient()
  const p = preview.data
  const path = file ?? dir
  // Pattern sample: relative paths spread over the folder by detection, else the browsed folder's
  // listing, the same query as the Data root step's browser
  const listing = useFsList(dir, 'source').data
  const detected = detect.data?.candidates.find((c) => c.adapter === 'nifti-files')?.sample
  const fileNames = useMemo(() => (detected?.length ? detected : (listing?.entries ?? []).filter((e) => e.kind === 'file').map((e) => e.name)), [detected, listing])
  const stems = useMemo(() => imageStems(options, file, fileNames), [options, file, fileNames])
  const auto = autoOptions(adapter, touched, options, stems, file || options.include ? [] : fileNames)
  const niftiOptions = auto ? { ...options, ...auto } : options
  const taken = (useRoots(pid).data ?? []).find((r) => r.alias === alias)
  const aliasKind = aliasProblem(alias, taken, prefill?.add ?? false, dir)
  const aliasError = aliasKind === 'invalid' ? t('import.aliasInvalid') : aliasKind === 'taken' ? t('import.aliasTaken', { alias, path: taken?.path ?? '' }) : null
  const failed = jobFailed(job?.status)

  useEffect(() => {
    if (job?.status === 'succeeded') {
      void qc.invalidateQueries({ queryKey: keys.project(pid) })
      void qc.invalidateQueries({ queryKey: keys.projects() })
      const cases = p?.counts.cases
      toast({ message: cases == null ? t('import.converted') : t('import.done', { cases }), tone: 'ok' })
      close()
    }
  }, [job?.status, qc, close, t, p?.counts.cases, pid])

  const pickAdapter = (d: { candidates: DetectCandidate[] }) => setAdapter(firstAdapter(d.candidates, prefill?.adapter))
  const runDetect = (target: string) => {
    setStep('detect')
    preview.reset()
    detect.mutate(target, { onSuccess: pickAdapter })
  }
  // "Create project from this" (Open mode) arrives with the path: detect at once
  useEffect(() => {
    if (prefill) detect.mutate(prefill.path, { onSuccess: pickAdapter })
    // once per mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runPreview = (a: ImportAdapter, nifti: NiftiOptions = niftiOptions) => {
    if (!path) return
    const req: PreviewRequest = { root: path, alias, adapter: a, add: prefill?.add ?? false }
    if (a === 'nifti-files') req.options = nifti
    if (a === 'metadata-v1' && reconstruct) req.options = { reconstruct_sidecars: true }
    preview.mutate(req, { onSuccess: () => setStep('preview') })
  }
  // DICOM sources go through the converter task; its rows are imported on success
  const runConvert = async () => {
    setConvertError(null)
    try {
      const settings = anonymize ? { anonymize: 'basic' } : {}
      const r = await api.startTaskRun(pid, { task_id: 'dicom.convert', settings, selection: { source: path } }, reviewer || undefined)
      setJobId(r.job_id)
      setStep('index')
    } catch (e) {
      setConvertError(e)
    }
  }
  const openInstead = () => {
    close()
    if (path) openPath(navigate, path)
  }

  const i = STEPS.indexOf(step)
  const enabled = canNext({ step, path, aliasOk: aliasError === null, upload, hasUploadedMetadata: files.metadata != null, adapter, previewPending: preview.isPending, preview: p, commitPending: commit.isPending })
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

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && (step !== 'index' || failed) && close()}
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
          pending={detect.isPending || preview.isPending}
          errors={[detect.isError ? detect.error : null, preview.isError ? preview.error : null, convertError]}
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
          cands={detect.data?.candidates ?? []}
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
          ignored={detect.data?.ignored}
        />
      ) : null}
      {step === 'preview' && p ? <PreviewStep p={p} /> : null}
      {step === 'index' ? <IndexStep job={job} failed={failed} /> : null}
    </Dialog>
  )
}
