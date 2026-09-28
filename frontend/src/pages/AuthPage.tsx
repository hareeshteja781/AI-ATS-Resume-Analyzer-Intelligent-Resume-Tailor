import { useState } from 'react'
import { ArrowRight, BriefcaseBusiness, LogIn, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

export function AuthPage() {
  const { login, devTestLogin, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // TEMPORARY LOCAL-DEVELOPMENT TEST LOGIN — remove with /auth/dev-test-login before public deployment.
  const handleTestLogin = async () => {
    setError('')
    setLoading(true)
    try {
      await devTestLogin()
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test login failed')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setLoading(true)

    try {
      if (mode === 'login') {
        await login(email, password)
      } else {
        await register(email, password)
      }
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-10">
      <div className="grid w-full max-w-6xl gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-[32px] border border-white/10 bg-white/5 p-8 text-white backdrop-blur-sm">
          <div className="mb-8 flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-500 text-xl font-bold">A</div>
            <div>
              <div className="text-xs uppercase tracking-[0.28em] text-indigo-300">ATS</div>
              <div className="text-2xl font-semibold">Resume Intelligence</div>
            </div>
          </div>

          <div className="space-y-6">
            <div>
              <div className="mb-2 inline-flex rounded-full border border-indigo-400/20 bg-indigo-500/10 px-3 py-1 text-xs font-medium text-indigo-200">
                Production-grade career optimization
              </div>
              <h1 className="text-4xl font-semibold leading-tight">Match, tailor, and export better resumes with confidence.</h1>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {[
                { icon: BriefcaseBusiness, label: 'Role-aligned ATS scoring' },
                { icon: ShieldCheck, label: 'Evidence-backed tailoring' },
              ].map(({ icon: Icon, label }) => (
                <div key={label} className="rounded-2xl border border-white/10 bg-slate-900/40 p-4">
                  <Icon className="mb-3 h-5 w-5 text-indigo-300" />
                  <p className="text-sm text-slate-200">{label}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <Card className="rounded-[28px] border-slate-200 p-2 shadow-2xl shadow-indigo-100">
          <CardHeader className="px-5 pb-3 pt-6">
            <CardTitle className="text-2xl">{mode === 'login' ? 'Sign in' : 'Create account'}</CardTitle>
          </CardHeader>
          <CardContent className="px-5 pb-6">
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 outline-none ring-0 transition focus:border-indigo-400"
                  placeholder="you@example.com"
                  required
                />
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 outline-none ring-0 transition focus:border-indigo-400"
                  placeholder="Enter your password"
                  required
                />
              </div>

              {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? 'Please wait…' : mode === 'login' ? 'Continue' : 'Create account'}
                <ArrowRight className="h-4 w-4" />
              </Button>

              {mode === 'login' && import.meta.env.DEV ? (
                <div className="flex items-center justify-center gap-2 pt-1">
                  <span className="text-[11px] text-slate-400">Local testing</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={handleTestLogin}
                    disabled={loading}
                    className="h-8 px-3 text-xs"
                  >
                    <LogIn className="mr-1.5 h-3.5 w-3.5" />
                    Test login
                  </Button>
                </div>
              ) : null}
            </form>

            <div className="mt-5 text-center text-sm text-slate-600">
              {mode === 'login' ? 'Need an account?' : 'Already have an account?'}{' '}
              <button type="button" className="font-semibold text-indigo-600" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
                {mode === 'login' ? 'Sign up' : 'Log in'}
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
