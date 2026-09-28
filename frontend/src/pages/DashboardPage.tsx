import { ArrowUpRight, Briefcase, FileText } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Shell } from '../components/layout/Shell'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { jobDescriptionApi, resumeApi } from '../lib/api'

export function DashboardPage() {
  const [resumes, setResumes] = useState<Array<Record<string, unknown>>>([])
  const [jobDescriptions, setJobDescriptions] = useState<Array<Record<string, unknown>>>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      try {
        const [resumeData, jdData] = await Promise.all([resumeApi.list(), jobDescriptionApi.list()])
        setResumes(resumeData)
        setJobDescriptions(jdData)
      } catch {
        setResumes([])
        setJobDescriptions([])
      } finally {
        setLoading(false)
      }
    }

    void loadData()
  }, [])

  const stats = useMemo(
    () => [
      { label: 'Resumes', value: String(resumes.length), helper: resumes.length ? 'Active documents' : 'No resumes yet' },
      { label: 'Job descriptions', value: String(jobDescriptions.length), helper: jobDescriptions.length ? 'Ready for ATS scoring' : 'No roles loaded yet' },
      { label: 'Workspace status', value: resumes.length && jobDescriptions.length ? 'Ready' : 'Waiting', helper: resumes.length && jobDescriptions.length ? 'Data available' : 'Needs source input' },
    ],
    [resumes.length, jobDescriptions.length],
  )

  return (
    <Shell>
      <div className="space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium uppercase tracking-[0.2em] text-indigo-600">Overview</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight text-slate-900">Your ATS workspace</h1>
          </div>
          <Link to="/analyze" className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-500">
            New analysis <ArrowUpRight className="h-4 w-4" />
          </Link>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {stats.map((stat) => (
            <Card key={stat.label} className="rounded-2xl">
              <CardContent className="pt-6">
                <div className="text-sm text-slate-500">{stat.label}</div>
                <div className="mt-3 text-3xl font-semibold">{stat.value}</div>
                <div className="mt-2 text-sm text-slate-500">{stat.helper}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.4fr_0.8fr]">
          <Card className="rounded-3xl">
            <CardHeader>
              <CardTitle>Recent project sources</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">Loading workspace…</div>
              ) : resumes.length || jobDescriptions.length ? (
                [
                  ...resumes.slice(0, 3).map((resume) => ({
                    title: String(resume.original_filename ?? resume.filename ?? 'Resume'),
                    subtitle: 'Resume source',
                    status: String(resume.status ?? 'processed'),
                    tone: 'bg-indigo-100 text-indigo-700',
                    icon: Briefcase,
                  })),
                  ...jobDescriptions.slice(0, 3).map((job) => ({
                    title: String(job.role_name ?? job.filename ?? 'Job description') + (job.company_name ? ' (' + String(job.company_name) + ')' : ''),
                    subtitle: 'Job description source',
                    status: String(job.status ?? 'processed'),
                    tone: 'bg-emerald-100 text-emerald-700',
                    icon: FileText,
                  })),
                ].slice(0, 4).map(({ title, subtitle, status, tone, icon: Icon }) => (
                  <div key={`${title}-${status}`} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-indigo-600 shadow-sm">
                        <Icon className="h-4 w-4" />
                      </div>
                      <div>
                        <div className="font-medium text-slate-900">{title}</div>
                        <div className="text-sm text-slate-500">{subtitle}</div>
                      </div>
                    </div>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>{status}</span>
                  </div>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
                  No resume or role sources yet. Upload a resume and paste a job description to begin.
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="rounded-3xl">
            <CardHeader>
              <CardTitle>Next actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {[
                'Upload a resume and target role',
                'Run ATS analysis with evidence',
                'Tailor with controlled, supported edits',
              ].map((item) => (
                <div key={item} className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                  {item}
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </Shell>
  )
}
