import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BarChart3,
  ChevronDown,
  ExternalLink,
  FileSearch,
  FileText,
  Lightbulb,
  Link2,
  Sparkles,
} from 'lucide-react'
import { analysisApi, jobDescriptionApi, resumeApi } from '../lib/api'
import { Shell } from '../components/layout/Shell'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { ResumeSelector } from '../components/ui/resume-selector'

type SectionName = 'Summary' | 'Skills' | 'Experience' | 'Projects' | 'Education' | 'Certifications' | 'Technical Skills' | 'Achievements' | 'Soft Skills' | 'Keywords' | 'ATS Structure' | 'Layout'

type SectionScore = {
  key: SectionName
  score: number
}

type ProjectMatch = Record<string, unknown>

export function AnalyzePage() {
  const [resumeFile, setResumeFile] = useState<File | null>(null)
  const [jdText, setJdText] = useState('')
  const [jdUrl, setJdUrl] = useState('')
  const [urlPreview, setUrlPreview] = useState<{ source_url: string; final_url: string; role_name?: string | null; text_content: string; structured_extraction?: Record<string, unknown> } | null>(null)
  const [urlPreviewText, setUrlPreviewText] = useState('')
  const [jdFile, setJdFile] = useState<File | null>(null)
  const [jdImages, setJdImages] = useState<File[]>([])
  const [jdMode, setJdMode] = useState<'text' | 'document' | 'url' | 'images'>('text')
  const [resumes, setResumes] = useState<Array<Record<string, unknown>>>([])
  const [jobDescriptions, setJobDescriptions] = useState<Array<Record<string, unknown>>>([])
  const [resumeId, setResumeId] = useState<number | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expandedSection, setExpandedSection] = useState<SectionName | null>(null)

  const canAnalyze = useMemo(() => Boolean(resumeId && jobId), [resumeId, jobId])

  const loadData = useCallback(async () => {
    try {
      const [resumeData, jdData] = await Promise.all([resumeApi.list(), jobDescriptionApi.list()])
      setResumes(resumeData)
      setJobDescriptions(jdData)
      if (resumeData[0]) setResumeId((current) => current ?? Number(resumeData[0].id))
      if (jdData[0]) {
        setJobId((current) => current ?? Number(jdData[0].id))
        const sourceType = String(jdData[0].source_type ?? '')
        setJdMode(sourceType === 'url' ? 'url' : sourceType === 'image' ? 'images' : sourceType === 'upload' ? 'document' : 'text')
      }
    } catch (err) {
      setResumes([])
      setJobDescriptions([])
      setError(err instanceof Error ? 'Unable to load saved sources: ' + err.message : 'Unable to load saved sources')
    }
  }, [])

  useEffect(() => {
    const frame = requestAnimationFrame(() => void loadData())
    return () => cancelAnimationFrame(frame)
  }, [loadData])

  const handleUploadResume = async () => {
    if (!resumeFile) return
    setLoading(true)
    try {
      const payload = await resumeApi.upload(resumeFile)
      setResumeId(Number(payload.id))
      setResumeFile(null)
      setError('')
      await loadData()
      setResumeId(Number(payload.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resume upload failed')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmitJobText = async () => {
    if (!jdText.trim()) return
    setLoading(true)
    try {
      const payload = await jobDescriptionApi.paste(jdText)
      setJdText('')
      setJobId(Number(payload.id))
      setError('')
      await loadData()
      setJobId(Number(payload.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Job description save failed')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmitJobUrl = async () => {
    if (!jdUrl.trim()) return
    setLoading(true)
    try {
      const payload = await jobDescriptionApi.previewUrl(jdUrl.trim())
      setUrlPreview(payload)
      setUrlPreviewText(payload.text_content)
      setJdMode('url')
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Job description URL import failed')
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmJobUrl = async () => {
    if (!urlPreview || !urlPreviewText.trim()) return
    setLoading(true)
    try {
      const payload = await jobDescriptionApi.confirmUrl(urlPreview.source_url, urlPreviewText)
      setJdUrl('')
      setUrlPreview(null)
      setUrlPreviewText('')
      setJobId(Number(payload.id))
      setError('')
      await loadData()
      setJobId(Number(payload.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Job description confirmation failed')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmitJobImages = async () => {
    if (!jdImages.length) return
    setLoading(true)
    try {
      const payload = await jobDescriptionApi.uploadImages(jdImages)
      setJdImages([])
      setJobId(Number(payload.id))
      setJdMode('images')
      setError('')
      await loadData()
      setJobId(Number(payload.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Job description image extraction failed')
    } finally {
      setLoading(false)
    }
  }

  const handleUploadJobDocument = async () => {
    if (!jdFile) return
    setLoading(true)
    try {
      const payload = await jobDescriptionApi.upload(jdFile)
      setJobId(Number(payload.id))
      setJdMode('document')
      setError('')
      await loadData()
      setJobId(Number(payload.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Job description document upload failed')
    } finally {
      setLoading(false)
    }
  }

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
        setResult(null)
        setExpandedSection(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Resume deletion failed')
    } finally {
      setLoading(false)
    }
  }

  const handleAnalyze = async () => {
    if (!resumeId || !jobId) return
    setLoading(true)
    try {
      setResult(await analysisApi.jobMatch(resumeId, jobId))
      setExpandedSection(null)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  const selectedJob = jobDescriptions.find((job) => Number(job.id) === jobId)
  const sectionDetails = (result?.section_details as Record<string, string[]> | undefined) ?? {}
  const projectMatches = (result?.project_matches as ProjectMatch[] | undefined) ?? []
  const layoutAnalysis = (result?.layout_analysis as Record<string, unknown> | undefined) ?? {}
  const benchmark = (result?.benchmark as Record<string, unknown> | undefined) ?? {}
  const benchmarkSkills = (benchmark.common_skills as Array<Record<string, unknown>> | undefined) ?? []
  const benchmarkResumeComparison = (benchmark.resume_comparison as Record<string, unknown> | undefined) ?? {}
  const selectedJobLabel = (() => {
    if (!selectedJob) return 'Selected job description'
    const role = String(selectedJob.role_name ?? selectedJob.filename ?? 'Job description')
    const company = String(selectedJob.company_name ?? '').trim()
    return company ? role + ' (' + company + ')' : role
  })()

  const sectionScores = useMemo<SectionScore[]>(() => {
    const details = (result?.section_details as Record<string, string[]> | undefined) ?? {}
    const raw = (result?.section_scores as Record<string, number> | undefined) ?? {}
    const present = (result?.present_sections as string[] | undefined) ?? []
    const labelMap: Record<string, SectionName> = {
      Summary: 'Summary',
      Skills: 'Skills',
      Experience: 'Experience',
      Projects: 'Projects',
      Education: 'Education',
      Certifications: 'Certifications',
      Achievements: 'Achievements',
      'Soft Skills': 'Soft Skills',
    }
    const entries: SectionScore[] = []
    const seen = new Set<string>()

    // New API: use only sections actually detected in the uploaded resume.
    // Backward-compatible fallback: derive them from non-zero section scores.
    const knownSections = ['Summary', 'Skills', 'Experience', 'Projects', 'Education', 'Certifications', 'Achievements', 'Soft Skills']
    const detailKeys = Object.keys(details).filter((key) => knownSections.includes(key))
    const detected = present.length
      ? present
      : detailKeys.length
        ? detailKeys
        : knownSections.filter((key) => raw[key] !== undefined && Number(raw[key]) > 0)

    for (const section of detected) {
      const label = labelMap[section] ?? (section as SectionName)
      if (label && !seen.has(label) && raw[label] !== undefined) {
        entries.push({ key: label, score: Number(raw[label] ?? 0) })
        seen.add(label)
      }
    }
    return entries
  }, [result])

  const matchSuggestions = [
    ...(((result?.partially_matched_skills as string[]) ?? []).map((skill) =>
      `Strengthen the Skills section with ${skill} only if you genuinely know/use it, and support it with real resume evidence.`
    )),
    ...(((result?.important_gaps as string[]) ?? []).map((gap) =>
      `Address the gap “${gap}” with a truthful project, experience, education, certification, or other relevant evidence.`
    )),
  ]

  const renderBar = (score: number, height = 'h-2.5') => (
    <div className={'overflow-hidden rounded-full bg-slate-200 ' + height}>
      <div
        className="h-full rounded-full bg-indigo-600 transition-all duration-500"
        style={{ width: Math.max(0, Math.min(100, score)) + '%' }}
      />
    </div>
  )

  return (
    <Shell>
      <div className="space-y-8 text-slate-900 dark:text-slate-100">
        <div>
          <p className="text-sm font-medium uppercase tracking-[0.2em] text-indigo-600">Analysis</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">ATS Score & Match Signals</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-500">
            Compare the actual resume content against the selected job description, section by section.
          </p>
        </div>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)]">
          <Card className="rounded-3xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileSearch className="h-5 w-5 text-indigo-600" /> Resume & JD intake
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <label className="block text-sm font-medium text-slate-700">Upload resume</label>
                  <span className="text-[11px] text-slate-400">(PDF or Word)</span>
                </div>
                <input
                  type="file"
                  accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={(event) => setResumeFile(event.target.files?.[0] ?? null)}
                  className="block w-full text-sm text-slate-600"
                />
                <Button className="mt-3" variant="secondary" onClick={handleUploadResume} disabled={!resumeFile || loading}>
                  Upload resume
                </Button>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Select resume</label>
                <ResumeSelector
                  resumes={resumes}
                  value={resumeId}
                  onChange={setResumeId}
                  onDelete={(id) => void handleDeleteResume(id)}
                  disabled={loading}
                />
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <label className="mb-2 block text-sm font-medium text-slate-700">Job description source</label>
                <select
                  aria-label="Job description source"
                  value={jdMode}
                  onChange={(event) => setJdMode(event.target.value as 'text' | 'document' | 'url' | 'images')}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 outline-none focus:border-indigo-400"
                >
                  <option value="text">Paste job description text</option>
                  <option value="document">Upload JD document</option>
                  <option value="url">Import from job URL</option>
                  <option value="images">Upload JD screenshots</option>
                </select>

                {jdMode === 'text' ? (
                  <div className="mt-4">
                    <textarea
                      value={jdText}
                      onChange={(event) => setJdText(event.target.value)}
                      rows={8}
                      className="w-full rounded-2xl border border-slate-200 bg-white p-3 outline-none focus:border-indigo-400"
                      placeholder="Paste the complete job description here..."
                    />
                    <Button className="mt-3" variant="secondary" onClick={handleSubmitJobText} disabled={!jdText.trim() || loading}>
                      Save job description
                    </Button>
                  </div>
                ) : jdMode === 'document' ? (
                  <div className="mt-4">
                    <input
                      aria-label="JD document file"
                      type="file"
                      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      onChange={(event) => setJdFile(event.target.files?.[0] ?? null)}
                      className="block w-full text-sm text-slate-600"
                    />
                    {jdFile ? <div className="mt-3 text-xs text-slate-500">Selected: {jdFile.name}</div> : null}
                    <Button className="mt-3" variant="secondary" onClick={handleUploadJobDocument} disabled={!jdFile || loading}>
                      {loading ? 'Extracting document…' : 'Extract JD document'}
                    </Button>
                    {selectedJob?.source_type === 'upload' ? (
                      <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">
                        <div className="font-semibold">Extracted job description</div>
                        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-2 text-slate-700">{String(selectedJob.text_content ?? 'No extracted text available.')}</pre>
                        <div className="mt-2">Processing status: {String(selectedJob.status ?? 'unknown')}</div>
                      </div>
                    ) : null}
                  </div>
                ) : jdMode === 'images' ? (
                  <div className="mt-4">
                    <input
                      type="file"
                      accept=".png,.jpg,.jpeg,image/png,image/jpeg"
                      multiple
                      onChange={(event) => setJdImages(Array.from(event.target.files ?? []))}
                      className="block w-full text-sm text-slate-600"
                    />
                    {jdImages.length ? (
                      <div className="mt-3 space-y-1 text-xs text-slate-500">
                        {jdImages.map((file) => <div key={file.name}>{file.name}</div>)}
                      </div>
                    ) : null}
                    <Button className="mt-3" variant="secondary" onClick={handleSubmitJobImages} disabled={!jdImages.length || loading}>
                      Extract screenshots
                    </Button>
                    {selectedJob?.source_type === 'image' ? (
                      <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                        Extracted content is saved for review before analysis.
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="mt-4">
                    <div className="flex flex-col gap-3 sm:flex-row">
                      <input
                        type="url"
                        value={jdUrl}
                        onChange={(event) => setJdUrl(event.target.value)}
                        className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 outline-none focus:border-indigo-400"
                        placeholder="https://company.com/jobs/software-engineer"
                      />
                      <Button variant="secondary" onClick={handleSubmitJobUrl} disabled={!jdUrl.trim() || loading}>
                        Preview URL
                      </Button>
                    </div>
                    <p className="mt-2 text-[11px] text-slate-400">Use a public job-posting URL.</p>
                    {urlPreview ? (
                      <div className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900">
                        <div className="font-semibold">Review extracted job description</div>
                        <div className="mt-1 break-all text-xs text-indigo-700">Source: {urlPreview.source_url}</div>
                        <div className="mt-1 text-xs text-indigo-700">Title: {urlPreview.role_name ?? 'Not detected'}</div>
                        {urlPreview.structured_extraction ? <div className="mt-2 text-xs text-indigo-700">Structured fields: {Object.entries(urlPreview.structured_extraction).filter(([, value]) => Array.isArray(value) ? value.length > 0 : Boolean(value)).map(([key]) => key.replaceAll('_', ' ')).join(', ') || 'None detected'}</div> : null}
                        <textarea
                          value={urlPreviewText}
                          onChange={(event) => setUrlPreviewText(event.target.value)}
                          rows={9}
                          className="mt-3 w-full rounded-xl border border-indigo-200 bg-white p-3 text-xs text-slate-800"
                        />
                        <div className="mt-3 flex gap-2">
                          <Button variant="secondary" onClick={() => void handleConfirmJobUrl()} disabled={!urlPreviewText.trim() || loading}>Confirm JD</Button>
                          <Button variant="secondary" onClick={() => { setUrlPreview(null); setUrlPreviewText('') }} disabled={loading}>Reject</Button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                )}

                {selectedJob ? (
                  <div className="mt-4 flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
                    {jdMode === 'url' ? <Link2 className="mt-0.5 h-4 w-4 shrink-0" /> : <FileText className="mt-0.5 h-4 w-4 shrink-0" />}
                    <div className="min-w-0">
                      <div className="font-semibold">Selected job</div>
                      <div className="mt-0.5 break-words">{selectedJobLabel}</div>
                      {String(selectedJob.source_type ?? '') === 'image' ? (
                        <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-emerald-200 bg-white p-2 text-[11px] text-slate-700">
                          {String(selectedJob.text_content ?? 'No extracted text available.')}
                        </pre>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </div>

              {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
            </CardContent>
          </Card>

          <Card className="rounded-3xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><BarChart3 className="h-5 w-5 text-indigo-600" /> Match summary</CardTitle>
            </CardHeader>
            <CardContent>
              {result ? (
                <div className="space-y-6">
                  <div className="flex items-end justify-between gap-4">
                    <div>
                      <div className="text-sm text-slate-500">Overall job match</div>
                      <div className="mt-1 text-5xl font-semibold text-indigo-600">{Number(result.job_match_score ?? 0).toFixed(0)}%</div>
                    </div>
                    <div className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
                      {String(result.truthfulness_status ?? 'review')}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="mb-4 flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">Section match</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">Calculated from your resume and the selected JD. Sections the JD does not specify are not evaluated and are excluded from the overall job-match score.</div>
                      </div>
                    </div>

                    <div className="space-y-3">
                      {sectionScores.map(({ key, score }) => {
                        const expanded = expandedSection === key
                        const sectionNotEvaluated = (sectionDetails[key] ?? []).some((detail) =>
                          detail.toLowerCase().includes('not evaluated')
                        )
                        return (
                          <div key={key} className="rounded-xl border border-slate-200 bg-white">
                            <button
                              type="button"
                              onClick={() => setExpandedSection(expanded ? null : key)}
                              className="w-full px-4 py-3 text-left"
                            >
                              <div className="flex items-center justify-between gap-3">
                                <span className="text-sm font-medium text-slate-800 dark:text-slate-100">{key}</span>
                                <div className="flex items-center gap-3">
                                  <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                                    {sectionNotEvaluated ? 'Not evaluated' : score.toFixed(0) + '%'}
                                  </span>
                                  <ChevronDown className={'h-4 w-4 text-slate-400 transition-transform ' + (expanded ? 'rotate-180' : '')} />
                                </div>
                              </div>
                              <div className="mt-2">{renderBar(sectionNotEvaluated ? 0 : score)}</div>
                            </button>

                            {expanded ? (
                              <div className="border-t border-slate-100 px-4 py-3">
                                {key === 'Projects' ? (
                                  projectMatches.length ? (
                                    <div className="space-y-3">
                                      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Project-by-project relevance</div>
                                      {projectMatches.map((project, index) => {
                                        const projectScore = Number(project.score ?? 0)
                                        return (
                                          <div key={String(project.name) + '-' + index} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                                            <div className="flex items-start justify-between gap-3">
                                              <div className="min-w-0">
                                                <div className="font-medium text-slate-800">{String(project.name ?? 'Project')}</div>
                                                {String(project.stack ?? '') ? <div className="mt-1 text-xs text-slate-500">{String(project.stack)}</div> : null}
                                              </div>
                                              <span className="shrink-0 text-sm font-semibold text-indigo-600">{projectScore.toFixed(0)}%</span>
                                            </div>
                                            <div className="mt-2">{renderBar(projectScore, 'h-2')}</div>
                                            {((project.matched_signals as string[] | undefined) ?? []).length ? (
                                              <div className="mt-3 text-xs text-emerald-700">Matched: {((project.matched_signals as string[]) ?? []).join(', ')}</div>
                                            ) : null}
                                            {((project.missing_signals as string[] | undefined) ?? []).length ? (
                                              <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                                                Gaps from the entire resume: {((project.missing_signals as string[]) ?? []).slice(0, 6).join(', ')}
                                              </div>
                                            ) : null}
                                            {((project.present_elsewhere as string[] | undefined) ?? []).length ? (
                                              <div className="mt-1 text-xs text-sky-700 dark:text-sky-300">
                                                Present elsewhere in resume: {((project.present_elsewhere as string[]) ?? []).slice(0, 6).join(', ')}
                                              </div>
                                            ) : null}
                                            {((project.evidence as string[] | undefined) ?? []).length ? (
                                              <div className="mt-2 rounded-lg bg-white p-2 text-xs leading-5 text-slate-600">{String(((project.evidence as string[]) ?? [])[0])}</div>
                                            ) : null}
                                          </div>
                                        )
                                      })}
                                    </div>
                                  ) : (
                                    <div className="text-sm text-slate-500">No individual project entries were detected.</div>
                                  )
                                ) : (
                                  <div className="space-y-2 text-sm text-slate-600 dark:text-slate-300">
                                    {(sectionDetails[key] ?? []).map((detail) => <div key={detail}>{detail}</div>)}
                                  </div>
                                )}
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-900/70 dark:bg-indigo-950/30">
                    <div className="mb-3 flex items-center gap-2">
                      <Lightbulb className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
                      <div className="text-sm font-semibold text-indigo-900 dark:text-indigo-100">Suggestions to improve the match</div>
                    </div>
                    <div className="space-y-2">
                      {matchSuggestions.length ? (
                        matchSuggestions.slice(0, 8).map((suggestion, index) => (
                          <div key={index} className="rounded-lg bg-white/70 p-3 text-sm text-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
                            {suggestion}
                          </div>
                        ))
                      ) : (
                        <div className="text-sm text-slate-600 dark:text-slate-300">No additional section changes are suggested from the current resume evidence.</div>
                      )}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-950">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">Role benchmark</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">Context from stored job descriptions in the same normalized role family. This does not change Job Match.</div>
                      </div>
                      <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                        {String(benchmark.data_sufficiency ?? 'INSUFFICIENT')}
                      </span>
                    </div>
                    <div className="mt-3 text-xs text-slate-500">
                      {String(benchmark.normalized_role_family ?? 'No role family detected')} · {String(benchmark.sample_size ?? 0)} stored role-labeled JD records
                    </div>
                    {benchmarkSkills.length ? (
                      <div className="mt-4">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Common role signals</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {benchmarkSkills.slice(0, 10).map((item) => <span key={String(item.item)} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700">{String(item.item)}</span>)}
                        </div>
                      </div>
                    ) : null}
                    {((benchmarkResumeComparison.benchmark_common_but_not_evidenced as string[] | undefined) ?? []).length ? (
                      <div className="mt-3 text-xs text-amber-700">Benchmark-common but not evidenced: {((benchmarkResumeComparison.benchmark_common_but_not_evidenced as string[]) ?? []).slice(0, 6).join(', ')}</div>
                    ) : null}
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-950">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">Layout assessment</div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">Separate from content matching.</div>
                      </div>
                      <div className="text-sm font-semibold text-indigo-600">{Number(layoutAnalysis.score ?? 0).toFixed(0)}%</div>
                    </div>
                    {renderBar(Number(layoutAnalysis.score ?? 0))}
                    <div className="mt-3 flex items-center gap-2">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${String(layoutAnalysis.status ?? '') === 'GOOD' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-800'}`}>
                        {String(layoutAnalysis.status ?? 'REVIEW').replaceAll('_', ' ')}
                      </span>
                    </div>

                    {((layoutAnalysis.diagnostics as string[] | undefined) ?? []).length ? (
                      <div className="mt-4 grid gap-2 sm:grid-cols-2">
                        {((layoutAnalysis.diagnostics as string[]) ?? []).map((item) => (
                          <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
                            {item}
                          </div>
                        ))}
                      </div>
                    ) : null}

                    {((layoutAnalysis.issues as string[] | undefined) ?? []).length ? (
                      <div className="mt-4 space-y-2">
                        {((layoutAnalysis.issues as string[]) ?? []).map((issue) => <div key={issue} className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/50 dark:text-amber-200">{issue}</div>)}
                      </div>
                    ) : null}

                    {((layoutAnalysis.recommendations as string[] | undefined) ?? []).length ? (
                      <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50 p-3">
                        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-indigo-700">
                          <Lightbulb className="h-4 w-4" /> Layout suggestions
                        </div>
                        <div className="mt-2 space-y-2 text-sm text-indigo-950 dark:text-indigo-100">
                          {((layoutAnalysis.recommendations as string[]) ?? []).length ? (
                            ((layoutAnalysis.recommendations as string[]) ?? []).map((item) => <div key={item}>{item}</div>)
                          ) : (
                            <div>No layout changes are currently recommended.</div>
                          )}
                        </div>
                      </div>
                    ) : null}
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                      <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Matched skills</div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {((result.matched_skills as string[]) ?? []).map((skill) => <span key={skill} className="rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-medium text-indigo-700">{skill}</span>)}
                        {!((result.matched_skills as string[]) ?? []).length ? <span className="text-sm text-slate-500">No direct skill matches found.</span> : null}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                      <div className="text-sm font-medium text-slate-800 dark:text-slate-100">Important gaps</div>
                      <div className="mt-3 space-y-2">
                        {((result.important_gaps as string[]) ?? []).slice(0, 6).map((gap) => <div key={gap} className="text-sm text-slate-600">• {gap}</div>)}
                        {!((result.important_gaps as string[]) ?? []).length ? <span className="text-sm text-slate-500">No major gaps detected.</span> : null}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex min-h-[560px] items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center">
                  <div className="max-w-md">
                    <BarChart3 className="mx-auto h-9 w-9 text-slate-400" />
                    <div className="mt-3 text-lg font-semibold text-slate-700">Section-level match analysis</div>
                    <div className="mt-2 text-sm leading-6 text-slate-500">
                      Run the analysis to calculate section scores from the actual resume and selected job description.
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-3">
          {selectedJob && jdMode === 'url' && selectedJob.url ? (
            <a
              href={String(selectedJob.url)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-slate-500 hover:text-slate-700"
            >
              <ExternalLink className="h-4 w-4" /> Open job posting
            </a>
          ) : null}
          <Button size="lg" onClick={handleAnalyze} disabled={!canAnalyze || loading} className="gap-2">
            <Sparkles className="h-4 w-4" />
            {loading ? 'Analyzing…' : 'Run ATS analysis'}
          </Button>
        </div>
      </div>
    </Shell>
  )
}
