import { useEffect, useState } from 'react'
import { FileStack, GitCompareArrows, Trash2 } from 'lucide-react'
import { resumeApi, versionApi } from '../lib/api'
import { Shell } from '../components/layout/Shell'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

type Version = Record<string, unknown>

export function VersionsPage() {
  const [resumes, setResumes] = useState<Version[]>([])
  const [versions, setVersions] = useState<Version[]>([])
  const [resumeId, setResumeId] = useState<number | null>(null)
  const [baseVersionId, setBaseVersionId] = useState<number | null>(null)
  const [targetVersionId, setTargetVersionId] = useState<number | null>(null)
  const [compareResult, setCompareResult] = useState<Version | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const applyVersionDefaults = (data: Version[]) => {
    setVersions(data)
    const master = data.find((item) => item.is_master)
    const tailored = data.find((item) => !item.is_master)
    const fallbackBase = master ?? data[data.length - 1]
    const fallbackTarget = tailored ?? data[0]
    setBaseVersionId(fallbackBase ? Number(fallbackBase.id) : null)
    setTargetVersionId(fallbackTarget ? Number(fallbackTarget.id) : null)
  }

  useEffect(() => {
    const initialize = async () => {
      try {
        const data = await resumeApi.list()
        setResumes(data)
        if (data[0]) setResumeId((current) => current ?? Number(data[0].id))
      } catch (err) {
        setResumes([])
        setError(err instanceof Error ? err.message : 'Unable to load resumes')
      }
    }
    void initialize()
  }, [])  
  useEffect(() => {
    if (!resumeId) return
    const loadVersions = async () => {
      try {
        const data = await versionApi.list(resumeId)
        applyVersionDefaults(data)
        setCompareResult(null)
        setError('')
      } catch (err) {
        setVersions([])
        setCompareResult(null)
        setError(err instanceof Error ? err.message : 'Unable to load versions')
      }
    }
    void loadVersions()
  }, [resumeId])

  const handleCompare = async () => {
    if (!baseVersionId || !targetVersionId || baseVersionId === targetVersionId) return
    setLoading(true)
    try {
      setCompareResult(await versionApi.compare(baseVersionId, targetVersionId))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed')
    } finally {
      setLoading(false)
    }
  }
  const handleDelete = async (version: Version) => {
    const id = Number(version.id)
    if (version.is_master) return
    const name = String(version.version_name ?? `Version ${id}`)
    if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return

    setLoading(true)
    try {
      const result = await versionApi.delete(id)
      setMessage(result.message)
      const data = await versionApi.list(resumeId as number)
      applyVersionDefaults(data)
      setCompareResult(null)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setLoading(false)
    }
  }

  const handleRestore = async (versionId: number) => {
    if (!resumeId) return
    setLoading(true)
    try {
      const result = await versionApi.restore(resumeId, versionId)
      setMessage(result.message)
      const data = await versionApi.list(resumeId)
      applyVersionDefaults(data)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Restore failed')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async (versionId: number, format: 'docx' | 'pdf') => {
    try {
      if (format === 'docx') await versionApi.downloadDocx(versionId)
      else await versionApi.downloadPdf(versionId)
      setMessage(`${format.toUpperCase()} download started`)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : `Unable to download ${format.toUpperCase()}`)
    }
  }
  return (
    <Shell>
      <div className="space-y-8">
        <div>
          <p className="text-sm font-medium uppercase tracking-[0.2em] text-indigo-600">Versions</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Resume version history</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-500">
            Keep the master resume intact, review tailored versions, and compare the complete documents side by side.
          </p>
        </div>

        <Card className="rounded-3xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileStack className="h-5 w-5 text-indigo-600" /> Version registry
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Resume</label>
              <select
                value={resumeId ?? ''}
                onChange={(event) => setResumeId(event.target.value ? Number(event.target.value) : null)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 outline-none focus:border-indigo-400"
              >
                <option value="">Choose a resume</option>
                {resumes.map((resume) => (
                  <option key={Number(resume.id)} value={Number(resume.id)}>
                    {String(resume.original_filename ?? resume.filename ?? `Resume ${resume.id}`)}
                  </option>
                ))}
              </select>
            </div>

            {message ? <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{message}</div> : null}
            {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

            <div className="space-y-3">
              {versions.length ? versions.map((version) => (
                <div key={String(version.id)} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 font-medium text-slate-900">
                        {String(version.version_name ?? 'Version')}
                        {version.is_master ? <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">MASTER</span> : null}
                      </div>
                      <div className="mt-1 text-sm text-slate-500">
                        {String(version.source_type ?? 'source')} · {String(version.status ?? 'ready')}
                      </div>
                      {version.created_at ? <div className="mt-1 text-xs text-slate-400">{String(version.created_at)}</div> : null}
                    </div>
                    <span className="rounded-full bg-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700">
                      {String(version.truthfulness_status ?? 'verified')}
                    </span>
                  </div>
                    {!version.is_master ? (
                      <div className="mt-1 text-sm text-slate-600">
                        {String(version.job_role_name ?? 'Role not recorded')}
                        {version.job_company_name ? ` · ${String(version.job_company_name)}` : ''}
                      </div>
                    ) : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" onClick={() => handleDownload(Number(version.id), 'docx')}>DOCX</Button>
                    <Button size="sm" variant="secondary" onClick={() => handleDownload(Number(version.id), 'pdf')}>PDF</Button>
                    <Button size="sm" variant="secondary" onClick={() => handleRestore(Number(version.id))}>Restore</Button>
                    {!version.is_master ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => void handleDelete(version)}
                        disabled={loading}
                        className="text-red-600 hover:text-red-700"
                      >
                        <Trash2 className="mr-1 h-4 w-4" /> Delete
                      </Button>
                    ) : null}
                  </div>
                </div>
              )) : (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-slate-500">
                  Choose a resume to view generated versions and exports.
                </div>
              )}
            </div>
          </CardContent>
        </Card>
        {versions.length >= 1 ? (
          <Card className="rounded-3xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <GitCompareArrows className="h-5 w-5 text-indigo-600" /> Compare complete resumes
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">Original / base version</label>
                  <select
                    value={baseVersionId ?? ''}
                    onChange={(event) => {
                      setBaseVersionId(event.target.value ? Number(event.target.value) : null)
                      setCompareResult(null)
                    }}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5"
                  >
                    {versions.map((version) => (
                      <option key={`base-${String(version.id)}`} value={Number(version.id)}>
                        {String(version.version_name ?? `Version ${version.id}`)}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">Tailored / target version</label>
                  <select
                    value={targetVersionId ?? ''}
                    onChange={(event) => {
                      setTargetVersionId(event.target.value ? Number(event.target.value) : null)
                      setCompareResult(null)
                    }}
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5"
                  >
                    {versions.map((version) => (
                      <option key={`target-${String(version.id)}`} value={Number(version.id)}>
                        {String(version.version_name ?? `Version ${version.id}`)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={() => void handleCompare()} disabled={!baseVersionId || !targetVersionId || baseVersionId === targetVersionId || loading}>
                  {loading ? 'Comparing…' : 'Compare'}
                </Button>
                {baseVersionId === targetVersionId ? <span className="text-sm text-amber-600">Choose two different versions.</span> : null}
              </div>

              {compareResult ? (
                <div className="space-y-5">
                  <div className="grid gap-5 xl:grid-cols-2">
                    <div className="min-w-0 rounded-2xl border border-slate-200 overflow-hidden">
                      <div className="border-b border-slate-200 bg-slate-100 px-4 py-3">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Original / base</div>
                        <div className="mt-1 font-semibold text-slate-900">{String(compareResult.base_version_name ?? 'Base version')}</div>
                      </div>
                      <pre className="max-h-[720px] overflow-auto whitespace-pre-wrap break-words bg-white p-5 text-sm leading-6 text-slate-800">
                        {String(compareResult.base_text ?? '')}
                      </pre>
                    </div>
                    <div className="min-w-0 rounded-2xl border border-indigo-200 overflow-hidden">
                      <div className="border-b border-indigo-200 bg-indigo-50 px-4 py-3">
                        <div className="text-xs font-semibold uppercase tracking-wide text-indigo-600">Tailored / target</div>
                        <div className="mt-1 font-semibold text-slate-900">{String(compareResult.target_version_name ?? 'Target version')}</div>
                      </div>
                      <pre className="max-h-[720px] overflow-auto whitespace-pre-wrap break-words bg-white p-5 text-sm leading-6 text-slate-800">
                        {String(compareResult.target_text ?? '')}
                      </pre>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="mb-3 text-sm font-semibold text-slate-800">Detected changes</div>
                    <div className="space-y-2">
                      {((compareResult.diff as Array<Record<string, string>>) ?? []).map((item, index) => (
                        <div key={index} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
                          <span className="font-semibold capitalize text-slate-700">{String(item.type ?? 'change')}</span>
                          <div className="mt-1 whitespace-pre-wrap break-words text-slate-600">{String(item.text ?? '')}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {((compareResult.validation_errors as string[]) ?? []).length ? (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                      {((compareResult.validation_errors as string[]) ?? []).join(' ')}
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-slate-500">
                  Compare two different versions to see the full original resume and the full tailored resume side by side.
                </div>
              )}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </Shell>
  )
}
