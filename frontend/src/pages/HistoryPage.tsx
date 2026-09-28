import { useEffect, useState } from 'react'
import { CalendarDays, FileText, History, Search } from 'lucide-react'
import { Shell } from '../components/layout/Shell'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { versionApi } from '../lib/api'

type HistoryItem = Record<string, unknown>

const displayName = (item: HistoryItem) => {
  const role = String(item.job_role_name ?? item.version_name ?? 'Untitled role')
  const company = String(item.job_company_name ?? '').trim()
  return company ? role + ' (' + company + ')' : role
}

export function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<HistoryItem | null>(null)
  const [resumePreviewUrl, setResumePreviewUrl] = useState('')
  const [loading, setLoading] = useState(true)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [error, setError] = useState('')
  const [previewError, setPreviewError] = useState('')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const data = await versionApi.history(query)
        setItems(data)
        setSelected((current) => {
          if (current && data.some((item) => Number(item.id) === Number(current.id))) {
            return data.find((item) => Number(item.id) === Number(current.id)) ?? current
          }
          return data[0] ?? null
        })
        setError('')
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to load tailoring history')
      } finally {
        setLoading(false)
      }
    }
    void load()
  }, [query])

  useEffect(() => {
    let objectUrl = ''
    const loadPreview = async () => {
      if (!selected) {
        setResumePreviewUrl('')
        return
      }
      setPreviewLoading(true)
      setPreviewError('')
      try {
        objectUrl = await versionApi.previewPdf(Number(selected.id))
        setResumePreviewUrl(objectUrl)
      } catch (err) {
        setResumePreviewUrl('')
        setPreviewError(err instanceof Error ? err.message : 'Resume preview could not be loaded')
      } finally {
        setPreviewLoading(false)
      }
    }
    void loadPreview()
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [selected])
  return (
    <Shell>
      <div className="space-y-8">
        <div>
          <p className="text-sm font-medium uppercase tracking-[0.2em] text-indigo-600 dark:text-indigo-400">History</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">Tailoring History</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-500 dark:text-slate-400">
            One current record per role and company. A new tailoring replaces the previous record for that exact target.
          </p>
        </div>

        <Card className="rounded-3xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Search className="h-5 w-5 text-indigo-600" /> Search roles and companies</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-slate-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by role or company..."
                className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-3 outline-none focus:border-indigo-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              />
            </div>
          </CardContent>
        </Card>

        {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200">{error}</div> : null}

        <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)]">
          <Card className="min-w-0 rounded-3xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-5 w-5 text-indigo-600" /> Saved tailorings
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {loading ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">Loading history…</div>
              ) : items.length ? (
                items.map((item) => {
                  const active = Number(selected?.id) === Number(item.id)
                  return (
                    <button
                      type="button"
                      key={String(item.id)}
                      onClick={() => setSelected(item)}
                      className={'w-full rounded-2xl border p-4 text-left transition ' + (
                        active
                          ? 'border-indigo-300 bg-indigo-50 text-slate-900 shadow-sm dark:border-indigo-500/70 dark:bg-indigo-950/50 dark:text-indigo-100'
                          : 'border-slate-200 bg-white text-slate-900 hover:border-indigo-200 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-indigo-800 dark:hover:bg-slate-800'
                      )}
                    >
                      <div className="font-semibold">{displayName(item)}</div>
                      <div className="mt-2 flex min-w-0 flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
                        <span className="break-words">{String(item.resume_filename ?? 'Resume')}</span>
                        {item.created_at ? (
                          <span className="inline-flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5" />{new Date(String(item.created_at)).toLocaleString()}</span>
                        ) : null}
                      </div>
                    </button>
                  )
                })
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                  {query ? 'No tailoring history matches that search.' : 'No finalized tailoring history yet.'}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="min-w-0 rounded-3xl">
            <CardHeader>
              <CardTitle className="break-words text-slate-900 dark:text-slate-100">
                {selected ? displayName(selected) : 'Select a tailoring'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {selected ? (
                <div className="min-w-0 space-y-6">
                  <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                    <div className="min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-900">
                      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Resume</div>
                      <div className="mt-1 break-words text-sm font-medium text-slate-800 dark:text-slate-100">{String(selected.resume_filename ?? 'Resume')}</div>
                    </div>
                    <div className="min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-900">
                      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Source</div>
                      <div className="mt-1 break-words text-sm font-medium text-slate-800 dark:text-slate-100">{String(selected.job_url ?? 'Pasted job description')}</div>
                    </div>
                  </div>

                  <section>
                    <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
                      <FileText className="h-4 w-4 text-indigo-600" /> Job description
                    </div>
                    {String(selected.job_source_html ?? '').trim() ? (
                      <iframe
                        title="Saved job description page"
                        srcDoc={String(selected.job_source_html)}
                        sandbox=""
                        className="h-[560px] w-full rounded-2xl border border-slate-200 bg-white dark:border-slate-700"
                      />
                    ) : (
                      <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap break-words rounded-2xl border border-slate-200 bg-white p-5 text-sm leading-6 text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200">
                        {String(selected.job_description_text ?? 'No job description text saved.')}
                      </pre>
                    )}
                  </section>

                  <section>
                    <div className="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-100">Rendered tailored resume</div>
                    {previewLoading ? (
                      <div className="flex h-[720px] items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">Preparing the rendered resume preview…</div>
                    ) : resumePreviewUrl ? (
                      <iframe
                        title="Rendered tailored resume"
                        src={resumePreviewUrl}
                        className="h-[720px] w-full rounded-2xl border border-slate-200 bg-white dark:border-slate-700"
                      />
                    ) : (
                      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/70 dark:bg-amber-950/40 dark:text-amber-200">
                        {previewError || 'A rendered preview is not available for this version.'}
                      </div>
                    )}
                  </section>

                </div>
              ) : (
                <div className="flex min-h-[560px] items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                  Select a saved tailoring from the left to see the complete job description and rendered tailored resume.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </Shell>
  )
}
