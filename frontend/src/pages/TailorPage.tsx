import { useEffect, useMemo, useRef, useState } from 'react'
import { renderAsync } from 'docx-preview'
import { AlertTriangle, Check, Download, Eye, Maximize2, Minimize2, X, Wand2 } from 'lucide-react'
import { downloadToSaveFile, jobDescriptionApi, pickSaveFile, resumeApi, tailoringApi, versionApi } from '../lib/api'
import { Shell } from '../components/layout/Shell'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { ResumeSelector } from '../components/ui/resume-selector'

type Source = Record<string, unknown>
type TailoringModification = Record<string, unknown>

const jobLabel = (job: Source | undefined) => {
  if (!job) return 'Selected role'
  const role = String(job.role_name ?? job.filename ?? 'Selected role')
  const company = String(job.company_name ?? '').trim()
  return company ? `${role} (${company})` : role
}

const changeSection = (item: TailoringModification) => {
  const action = String(item.action_type ?? '')
  if (action === 'ADD_SUMMARY') return 'Summary'
  const requirement = String(item.target_jd_requirement ?? '').toLowerCase()
  if (/(python|fastapi|sql|docker|skill|technology)/.test(requirement)) return 'Skills / Experience'
  if (/(degree|education|certif)/.test(requirement)) return 'Education / Certifications'
  return 'Experience / Projects'
}

type DocumentFormat = 'docx' | 'pdf'

function ResumeDocumentViewer({
  blob,
  format,
  title,
}: {
  blob: Blob | null
  format: DocumentFormat
  title: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const container = containerRef.current
    if (format !== 'docx' || !blob || !container) return

    setError('')
    container.innerHTML = ''
    void renderAsync(blob, container, undefined, {
      inWrapper: true,
      breakPages: true,
      ignoreWidth: false,
      ignoreHeight: false,
      ignoreLastRenderedPageBreak: false,
      useBase64URL: true,
      renderHeaders: true,
      renderFooters: true,
      renderFootnotes: true,
      renderEndnotes: true,
    }).catch(() => {
      if (active) setError('The DOCX preview could not be rendered.')
    })

    return () => {
      active = false
      container.innerHTML = ''
    }
  }, [blob, format])

  if (!blob) {
    return (
      <div className="flex h-[780px] items-center justify-center rounded-xl bg-slate-100 text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
        Preparing document preview…
      </div>
    )
  }

  if (format === 'pdf') {
    return <PdfBlobViewer blob={blob} title={title} />
  }

  return (
    <div className="h-[780px] overflow-auto rounded-xl bg-slate-200 p-4 dark:bg-slate-950">
      {error ? (
        <div className="flex h-full items-center justify-center text-sm text-red-600 dark:text-red-300">{error}</div>
      ) : (
        <div ref={containerRef} className="mx-auto min-h-full w-fit" />
      )}
    </div>
  )
}

function PdfBlobViewer({ blob, title }: { blob: Blob; title: string }) {
  const url = useMemo(() => URL.createObjectURL(blob), [blob])

  useEffect(() => () => URL.revokeObjectURL(url), [url])

  return url ? (
    <iframe
      title={title}
      src={url}
      className="h-[780px] w-full rounded-xl border-0 bg-white"
    />
  ) : (
    <div className="flex h-[780px] items-center justify-center rounded-xl bg-white text-sm text-slate-500">Preparing PDF preview…</div>
  )
}

export function TailorPage() {
  const [resumes, setResumes] = useState<Source[]>([])
  const [jobDescriptions, setJobDescriptions] = useState<Source[]>([])
  const [resumeId, setResumeId] = useState<number | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const [tailoring, setTailoring] = useState<Record<string, unknown> | null>(null)
  const [acceptedChangeIds, setAcceptedChangeIds] = useState<string[]>([])
  const [createdVersion, setCreatedVersion] = useState<Source | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [originalDocument, setOriginalDocument] = useState<Blob | null>(null)
  const [tailoredDocument, setTailoredDocument] = useState<Blob | null>(null)
  const [documentFormat, setDocumentFormat] = useState<DocumentFormat>('docx')
  const [documentLoading, setDocumentLoading] = useState(false)
  const [isComparisonFullscreen, setIsComparisonFullscreen] = useState(false)
  const comparisonRef = useRef<HTMLElement>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const initialize = async () => {
      try {
        const [resumeData, jdData] = await Promise.all([resumeApi.list(), jobDescriptionApi.list()])
        setResumes(resumeData)
        setJobDescriptions(jdData)
        if (resumeData[0]) setResumeId(Number(resumeData[0].id))
        if (jdData[0]) setJobId(Number(jdData[0].id))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to load saved sources')
      }
    }
    void initialize()
  }, [])

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsComparisonFullscreen(document.fullscreenElement === comparisonRef.current)
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  const handleDeleteResume = async (targetResumeId: number) => {
    const target = resumes.find((resume) => Number(resume.id) === targetResumeId)
    if (!target) return
    const name = String(target.original_filename ?? target.filename ?? 'Resume')
    if (!window.confirm(`Permanently delete "${name}"? This removes the uploaded file and all data derived from this resume.`)) return

    setLoading(true)
    setError('')
    try {
      await resumeApi.delete(targetResumeId)
      const remaining = resumes.filter((resume) => Number(resume.id) !== targetResumeId)
      setResumes(remaining)
      if (resumeId === targetResumeId) {
        setResumeId(remaining[0] ? Number(remaining[0].id) : null)
        setTailoring(null)
        setAcceptedChangeIds([])
        setCreatedVersion(null)
        setOriginalDocument(null)
        setTailoredDocument(null)
        if (previewUrl) URL.revokeObjectURL(previewUrl)
        setPreviewUrl('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resume deletion failed')
    } finally {
      setLoading(false)
    }
  }

  const toggleComparisonFullscreen = async () => {
    if (!comparisonRef.current) return
    setError('')
    try {
      if (document.fullscreenElement === comparisonRef.current) {
        await document.exitFullscreen()
      } else if (!document.fullscreenElement) {
        await comparisonRef.current.requestFullscreen()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to change comparison full screen mode')
    }
  }

  const selectedJob = jobDescriptions.find((item) => Number(item.id) === jobId)
  const selectedResume = resumes.find((item) => Number(item.id) === resumeId)

  const loadDocumentPreviews = async (selectedChanges: string[]) => {
    if (!resumeId || !jobId || !selectedResume) return

    setDocumentLoading(true)
    try {
      const isPdf =
        String(selectedResume.content_type ?? '').toLowerCase().includes('pdf')
        || String(selectedResume.original_filename ?? selectedResume.filename ?? '').toLowerCase().endsWith('.pdf')
      const format: DocumentFormat = isPdf ? 'pdf' : 'docx'
      const [originalBlob, tailoredBlob] = await Promise.all([
        resumeApi.preview(resumeId),
        tailoringApi.documentPreview(resumeId, jobId, format, selectedChanges),
      ])
      setDocumentFormat(format)
      setOriginalDocument(originalBlob)
      setTailoredDocument(tailoredBlob)
    } catch (err) {
      setOriginalDocument(null)
      setTailoredDocument(null)
      setError(err instanceof Error ? err.message : 'Unable to load document comparison')
    } finally {
      setDocumentLoading(false)
    }
  }

  const handlePreview = async () => {
    if (!resumeId || !jobId) return
    setLoading(true)
    setError('')
    try {
      const payload = await tailoringApi.preview(resumeId, jobId)
      setTailoring(payload)
      const changes = (payload.modifications as TailoringModification[] | undefined) ?? []
      const persistedAccepted = changes
        .filter((item) => String(item.decision ?? '') === 'ACCEPTED')
        .map((item) => String(item.id))
      const pendingSupported = changes
        .filter((item) => {
          const decision = String(item.decision ?? '').toUpperCase()
          const truthfulness = String(item.truthfulness_status ?? '').toUpperCase()
          const proposed = String(item.proposed_content ?? '').trim()
          return decision !== 'REJECTED' && truthfulness !== 'UNSUPPORTED' && Boolean(proposed)
        })
        .map((item) => String(item.id))
      setAcceptedChangeIds(persistedAccepted)
      setCreatedVersion(null)
      if (previewUrl) URL.revokeObjectURL(previewUrl)
      setPreviewUrl('')
      await loadDocumentPreviews([...new Set([...persistedAccepted, ...pendingSupported])])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Tailored resume generation failed')
      setCreatedVersion(null)
      setPreviewUrl('')
    } finally {
      setLoading(false)
    }
  }

  const handleDecision = async (changeId: string, accepted: boolean) => {
    if (!resumeId || !jobId) return
    const next = accepted
      ? [...new Set([...acceptedChangeIds, changeId])]
      : acceptedChangeIds.filter((id) => id !== changeId)
    setLoading(true)
    setError('')
    try {
      await tailoringApi.decide(changeId, accepted)
      await tailoringApi.finalizeText(resumeId, jobId, next)
      setAcceptedChangeIds(next)
      setCreatedVersion(null)
      setPreviewUrl('')
      await loadDocumentPreviews(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to apply change decision')
    } finally {
      setLoading(false)
    }
  }

  const handleBulkDecision = async (accepted: boolean) => {
    if (!resumeId || !jobId || !modifications.length) return

    const eligibleChanges = modifications.filter((item) => {
      const proposed = String(item.proposed_content ?? '').trim()
      const truthfulness = String(item.truthfulness_status ?? '').toUpperCase()
      return Boolean(proposed) && truthfulness !== 'UNSUPPORTED'
    })
    if (!eligibleChanges.length) return

    setLoading(true)
    setError('')
    try {
      await Promise.all(
        eligibleChanges.map((item) => tailoringApi.decide(String(item.id), accepted)),
      )
      const next = accepted
        ? eligibleChanges.map((item) => String(item.id))
        : []
      await tailoringApi.finalizeText(resumeId, jobId, next)
      setAcceptedChangeIds(next)
      setCreatedVersion(null)
      setPreviewUrl('')
      await loadDocumentPreviews(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to apply the bulk tailoring decision')
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (changeId: string) => {
    setLoading(true)
    setError('')
    try {
      await tailoringApi.decide(changeId, undefined, true)
      await handlePreview()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to verify change')
      setLoading(false)
    }
  }

  const handleSaveVersion = async () => {
    if (!resumeId || !jobId || !tailoring) return
    setLoading(true)
    setError('')
    try {
      const version = await versionApi.createTailored(resumeId, jobId, jobLabel(selectedJob), acceptedChangeIds)
      const finalizedVersion = await versionApi.finalize(Number(version.id), resumeId)
      setCreatedVersion(finalizedVersion)
      if (previewUrl) URL.revokeObjectURL(previewUrl)
      setPreviewUrl(await versionApi.previewPdf(Number(finalizedVersion.id)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save tailored version')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async (format: 'docx' | 'pdf') => {
    if (!createdVersion) {
      setError('Generate the tailored resume first.')
      return
    }

    const suggestedFilename = `${String(createdVersion.version_name ?? 'tailored-resume')}.${format}`
    const mimeType = format === 'docx'
      ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      : 'application/pdf'
    const description = format === 'docx' ? 'Microsoft Word document' : 'PDF document'

    setError('')
    try {
      // Open the native save dialog before network work, so the browser
      // preserves the button's user activation.
      const saveHandle = await pickSaveFile(suggestedFilename, description, mimeType, `.${format}`)
      if (!saveHandle && format === 'docx') {
        throw new Error('Your browser did not allow the secure Save File dialog. Please use the latest Chrome or Edge and try again.')
      }

      setLoading(true)
      if (saveHandle) {
        await downloadToSaveFile(
          `/resume-versions/${Number(createdVersion.id)}/download/${format}`,
          saveHandle,
        )
      } else if (format === 'pdf') {
        await versionApi.downloadPdf(Number(createdVersion.id), suggestedFilename)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : `Unable to download ${format.toUpperCase()}`)
    } finally {
      setLoading(false)
    }
  }

  const modifications = ((tailoring?.modifications as TailoringModification[] | undefined) ?? [])
  const tailoringChanges = modifications.filter((item) => {
    const proposed = String(item.proposed_content ?? '').trim()
    const category = String(item.change_category ?? '').toUpperCase()
    return Boolean(proposed) && category !== 'KEEP' && category !== 'USER_REVIEW'
  })
  const availableKeywords = ((tailoring?.available_keywords as TailoringModification[] | undefined) ?? [])
  const unsupported = modifications.filter(
    (item) => String(item.truthfulness_status ?? '') === 'UNSUPPORTED',
  )
  const autoApplied = tailoringChanges.filter(
    (item) => String(item.decision ?? '') === 'ACCEPTED',
  )
  const selectedModificationIds = new Set(acceptedChangeIds)
  const bulkEligibleChanges = tailoringChanges.filter((item) => {
    const proposed = String(item.proposed_content ?? '').trim()
    const truthfulness = String(item.truthfulness_status ?? '').toUpperCase()
    return Boolean(proposed) && truthfulness !== 'UNSUPPORTED'
  })
  const allBulkAccepted =
    bulkEligibleChanges.length > 0 &&
    bulkEligibleChanges.every((item) => selectedModificationIds.has(String(item.id)))

  return (
    <Shell>
      <div className="space-y-8 text-slate-900 dark:text-slate-100">
        <div>
          <p className="text-sm font-medium uppercase tracking-[0.2em] text-indigo-600 dark:text-indigo-400">Tailoring</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Guided resume optimization</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-500 dark:text-slate-400">
            The application always generates a tailored result first. Missing evidence is reported afterward as a review item instead of blocking generation.
          </p>
        </div>

        <Card className="rounded-3xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Wand2 className="h-5 w-5 text-indigo-600" /> Tailored resume
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">Resume</label>
                <ResumeSelector
                  resumes={resumes}
                  value={resumeId}
                  onChange={setResumeId}
                  onDelete={(id) => void handleDeleteResume(id)}
                  disabled={loading}
                  dark
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">Job description</label>
                <select
                  value={jobId ?? ''}
                  onChange={(event) => setJobId(event.target.value ? Number(event.target.value) : null)}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                >
                  <option value="">Choose a role</option>
                  {jobDescriptions.map((job) => (
                    <option key={Number(job.id)} value={Number(job.id)}>
                      {jobLabel(job)}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {selectedResume ? (
              <div className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-900">
                <span className="font-medium">Resume:</span> {String(selectedResume.original_filename ?? selectedResume.filename ?? 'Resume')}
              </div>
            ) : null}

            {error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200">
                {error}
              </div>
            ) : null}

            <Button onClick={() => void handlePreview()} disabled={!resumeId || !jobId || loading}>
              {loading ? 'Generating tailored resume…' : 'Generate tailored resume'}
            </Button>

            {tailoring ? (
              <>
                <section
                  ref={comparisonRef}
                  className={`space-y-4 bg-transparent p-0 ${isComparisonFullscreen ? 'min-h-screen overflow-auto bg-slate-950 p-6' : ''}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-lg font-semibold">Document comparison</div>
                      <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                        Original and tailored resumes are rendered from the actual uploaded document format.
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => void toggleComparisonFullscreen()}
                      disabled={!originalDocument || !tailoredDocument || documentLoading}
                    >
                      {isComparisonFullscreen ? (
                        <Minimize2 className="mr-1.5 h-4 w-4" />
                      ) : (
                        <Maximize2 className="mr-1.5 h-4 w-4" />
                      )}
                      {isComparisonFullscreen ? 'Exit full screen' : 'Full screen comparison'}
                    </Button>
                  </div>
                  <div className="grid gap-5 lg:grid-cols-2">
                    <div className="min-w-0 rounded-2xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900">
                      <div className="mb-3 flex items-center justify-between gap-3 px-1">
                        <div className="text-sm font-semibold">Original Resume</div>
                        <span className="rounded-full bg-slate-200 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                          {documentFormat}
                        </span>
                      </div>
                      <ResumeDocumentViewer blob={originalDocument} format={documentFormat} title="Original resume" />
                    </div>

                    <div className="min-w-0 rounded-2xl border border-indigo-200 bg-indigo-50/50 p-3 dark:border-indigo-900/70 dark:bg-indigo-950/20">
                      <div className="mb-3 flex items-center justify-between gap-3 px-1">
                        <div className="text-sm font-semibold">Tailored Resume</div>
                        <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-300">
                          {documentFormat}
                        </span>
                      </div>
                      {documentLoading ? (
                        <div className="flex h-[780px] items-center justify-center rounded-xl bg-white text-sm text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                          Updating tailored document…
                        </div>
                      ) : (
                        <ResumeDocumentViewer blob={tailoredDocument} format={documentFormat} title="Tailored resume" />
                      )}
                    </div>
                  </div>
                </section>

                <section className="rounded-2xl border border-indigo-200 bg-indigo-50/60 p-4 dark:border-indigo-900/70 dark:bg-indigo-950/30">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <div className="text-sm font-semibold">Tailoring changes</div>
                    {bulkEligibleChanges.length ? (
                      <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-indigo-200 bg-white px-3 py-2 text-xs font-medium text-indigo-900 dark:border-indigo-900/70 dark:bg-slate-950 dark:text-indigo-200">
                        <input
                          type="checkbox"
                          checked={allBulkAccepted}
                          disabled={loading}
                          onChange={(event) => void handleBulkDecision(event.target.checked)}
                          className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                        />
                        Accept all changes
                      </label>
                    ) : null}
                  </div>
                  <div className="space-y-3">
                    {tailoringChanges.length ? tailoringChanges.map((item, index) => {
                      const id = String(item.id ?? index)
                      const hasText = Boolean(String(item.proposed_content ?? '').trim())
                      const accepted = selectedModificationIds.has(id)
                      return (
                        <div key={id} className="rounded-xl border border-slate-200 bg-white p-3 text-xs dark:border-slate-700 dark:bg-slate-950">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-indigo-700 dark:text-indigo-300">{changeSection(item)}</span>
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">{String(item.change_category ?? 'USER_REVIEW')}</span>
                          </div>
                          <div className="mt-2 text-slate-500">Reason: {String(item.reason ?? 'No reason provided.')}</div>
                          <div className="mt-1 text-slate-500">Status: {String(item.truthfulness_status ?? 'REQUIRES_REVIEW')} · Decision: {String(item.decision ?? 'PENDING')}</div>
                          <div className="mt-3 grid gap-2">
                            <div><div className="font-semibold text-slate-500">Original</div><div className="mt-1 rounded-lg bg-rose-50 p-2 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200">{String(item.original_content ?? 'No original text')}</div></div>
                            <div><div className="font-semibold text-slate-500">Tailored</div><div className="mt-1 rounded-lg bg-emerald-50 p-2 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">{String(item.proposed_content ?? 'Review only; no automatic text inserted')}</div></div>
                          </div>
                          {hasText ? (
                            <div className="mt-3 flex gap-2">
                              <Button size="sm" variant={accepted ? 'default' : 'secondary'} onClick={() => void handleDecision(id, true)} disabled={loading}>
                                <Check className="mr-1 h-3.5 w-3.5" /> Accept
                              </Button>
                              <Button size="sm" variant={!accepted ? 'default' : 'secondary'} onClick={() => void handleDecision(id, false)} disabled={loading}>
                                <X className="mr-1 h-3.5 w-3.5" /> Reject
                              </Button>
                              {String(item.truthfulness_status ?? '') === 'REQUIRES_REVIEW' && item.user_verified !== true ? (
                                <Button size="sm" variant="secondary" onClick={() => void handleVerify(id)} disabled={loading}>
                                  Verify evidence
                                </Button>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      )
                    }) : <div className="text-sm text-slate-600">No tailored wording changes are required for the matched requirements.</div>}
                  </div>
                </section>

                {availableKeywords.length ? (
                  <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-950">
                    <div className="mb-3 text-sm font-semibold">ATS keyword selection</div>
                    <div className="flex flex-wrap gap-2">
                      {availableKeywords.map((keyword, index) => {
                        const match = modifications.find((item) => String(item.target_jd_requirement ?? '') === String(keyword.keyword ?? ''))
                        const id = match ? String(match.id) : ''
                        return (
                          <label key={String(keyword.id ?? index)} className="flex items-center gap-2 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs dark:border-slate-700">
                            <input type="checkbox" checked={keyword.selected === true} disabled={!id || loading} onChange={(event) => { if (id) void handleDecision(id, event.target.checked) }} />
                            {String(keyword.keyword ?? '')}
                          </label>
                        )
                      })}
                    </div>
                  </section>
                ) : null}

                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => void handleSaveVersion()} disabled={loading || Boolean(createdVersion)}>
                    Save Version
                  </Button>
                  {createdVersion && previewUrl ? <span className="self-center text-sm text-emerald-700">Saved tailored artifact ready.</span> : null}
                </div>

                {createdVersion && previewUrl ? <section>
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Eye className="h-4 w-4 text-indigo-600" /> Final preview</div>
                  <iframe title="Rendered tailored resume" src={previewUrl} className="h-[850px] w-full rounded-2xl border border-slate-200 bg-white dark:border-slate-700" />
                </section> : null}

                {createdVersion ? <div className="rounded-2xl border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-900/70 dark:bg-indigo-950/30">
                  <div className="text-sm font-semibold text-indigo-900 dark:text-indigo-100">Download</div>
                  <div className="mt-1 text-sm text-indigo-800 dark:text-indigo-200">
                    Both formats are available regardless of the original upload format.
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" onClick={() => void handleDownload('docx')} disabled={loading}>
                      <Download className="mr-1.5 h-4 w-4" /> Download DOCX
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => void handleDownload('pdf')} disabled={loading}>
                      <Download className="mr-1.5 h-4 w-4" /> Download PDF
                    </Button>
                  </div>
                </div> : null}

                <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-950">
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
                    <AlertTriangle className="h-4 w-4 text-amber-600" /> Suggestions & evidence review
                  </div>

                  {autoApplied.length ? (
                    <div className="space-y-3">
                      <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                        Accepted evidence-backed changes
                      </div>
                      {autoApplied.map((item, index) => (
                        <div key={String(item.id ?? index)} className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm dark:border-emerald-900/70 dark:bg-emerald-950/30">
                          <div className="font-semibold text-emerald-900 dark:text-emerald-100">
                            {String(item.change_category ?? 'Resume adjustment')}
                          </div>
                          <div className="mt-1 text-emerald-800 dark:text-emerald-200">
                            {String(item.reason ?? 'Aligned to the selected job description.')}
                          </div>
                          <div className="mt-2 text-xs text-emerald-700 dark:text-emerald-300">
                            Requirement: {String(item.target_jd_requirement ?? '')}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {unsupported.length ? (
                    <div className="mt-5 space-y-3">
                      <div className="text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
                        Added/review items with no direct evidence
                      </div>
                      {unsupported.map((item, index) => (
                        <div key={String(item.id ?? index)} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900/70 dark:bg-amber-950/30">
                          <div className="font-semibold text-amber-900 dark:text-amber-100">
                            {String(item.target_jd_requirement ?? 'Requirement')}
                          </div>
                          <div className="mt-1 text-amber-800 dark:text-amber-200">
                            {String(item.reason ?? 'No direct evidence was found in the original resume.')}
                          </div>
                          <div className="mt-2 text-amber-900 dark:text-amber-100">
                            {String(item.suggested_action ?? 'Review this requirement and add genuine supporting evidence when available.')}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {!autoApplied.length && !unsupported.length ? (
                    <div className="text-sm text-slate-600 dark:text-slate-300">
                      No additional changes were required for this tailoring.
                    </div>
                  ) : null}

                  <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-900">
                    Only persisted accepted supported changes, or explicitly user-verified changes, are included in the tailored result.
                  </div>
                </section>
              </>
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                Choose a resume and job description, then generate the tailored resume.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </Shell>
  )
}
