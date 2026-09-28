import { BarChart3, FileText, LayoutDashboard, LogOut, Settings, Sparkles, Upload, Users } from 'lucide-react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/useAuth'
import { Button } from '../ui/button'

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/analyze', label: 'Analyze', icon: BarChart3 },
  { to: '/tailor', label: 'Tailor', icon: Sparkles },
  { to: '/versions', label: 'Versions', icon: FileText },
  { to: '/history', label: 'History', icon: FileText },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Shell({ children }: { children: React.ReactNode }) {
  const { logout, user } = useAuth()
  const navigate = useNavigate()

  const handleSignOut = () => {
    logout()
    navigate('/auth')
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="fixed inset-y-0 left-0 w-72 border-r border-slate-200 bg-white/90 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/90">
        <div className="flex h-full flex-col p-5">
          <div className="mb-8 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-600 text-lg font-bold text-white shadow-lg shadow-indigo-200">
              A
            </div>
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-indigo-600">ATS</div>
              <div className="text-xl font-semibold">Resume AI</div>
            </div>
          </div>

          <nav className="space-y-2">
            {navItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-xl px-3 py-2.5 font-medium transition ${
                    isActive ? 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200 dark:bg-indigo-950/50 dark:text-indigo-200 dark:ring-indigo-800' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900'
                  }`
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="mt-auto rounded-2xl border border-indigo-100 bg-indigo-50 p-4 dark:border-indigo-900/60 dark:bg-indigo-950/40">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-indigo-700">
              <Upload className="h-4 w-4" />
              Uploads ready
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-300">Keep resume and JD sources aligned before each match cycle.</p>
          </div>

          <div className="mt-5 flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center gap-2 text-sm">
              <Users className="h-4 w-4 text-slate-500" />
              {user?.email ?? 'Account'}
            </div>
            <Button variant="ghost" size="sm" onClick={handleSignOut} className="h-8 w-8 p-0">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </aside>

      <main className="ml-72 min-h-screen p-8">
        {children}
      </main>
    </div>
  )
}
