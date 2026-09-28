import { useEffect, useState } from 'react'
import { Monitor, Moon, Palette, Settings, Sun } from 'lucide-react'
import { Shell } from '../components/layout/Shell'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

type Theme = 'light' | 'dark' | 'system'

function applyTheme(theme: Theme) {
  const root = document.documentElement
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  root.classList.toggle('dark', dark)
  root.style.colorScheme = dark ? 'dark' : 'light'
}

export function SettingsPage() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem('ats_theme') as Theme | null
    return saved === 'dark' || saved === 'system' || saved === 'light' ? saved : 'light'
  })

  const handleThemeChange = (nextTheme: Theme) => {
    setTheme(nextTheme)
    applyTheme(nextTheme)
    localStorage.setItem('ats_theme', nextTheme)
  }

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  return (
    <Shell>
      <div className="space-y-8">
        <div>
          <p className="text-sm font-medium uppercase tracking-[0.2em] text-indigo-600">Settings</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Workspace preferences</h1>
          <p className="mt-2 text-slate-500 dark:text-slate-400">Control the appearance and behavior of your ATS workspace.</p>
        </div>

        <Card className="rounded-3xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Palette className="h-5 w-5 text-indigo-600" />
              Appearance
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {[
              { value: 'light' as Theme, label: 'Light', icon: Sun, description: 'Use the light workspace theme.' },
              { value: 'dark' as Theme, label: 'Dark', icon: Moon, description: 'Use a dark workspace theme.' },
              { value: 'system' as Theme, label: 'System', icon: Monitor, description: 'Follow your Windows/browser theme preference.' },
            ].map(({ value, label, icon: Icon, description }) => (
              <button
                key={value}
                type="button"
                onClick={() => handleThemeChange(value)}
                className={`flex w-full items-center gap-4 rounded-2xl border p-4 text-left transition ${
                  theme === value
                    ? 'border-indigo-300 bg-indigo-50 text-slate-900 shadow-sm dark:border-indigo-500/60 dark:bg-indigo-950/40 dark:text-indigo-100'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800'
                }`}
              >
                <Icon className="h-5 w-5 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{label}</span>
                  <span className="mt-1 block text-sm text-slate-500 dark:text-slate-400">{description}</span>
                </span>
                <span className={`h-4 w-4 rounded-full border-2 ${
                  theme === value ? 'border-indigo-600 bg-indigo-600' : 'border-slate-300 dark:border-slate-600'
                }`} />
              </button>
            ))}
          </CardContent>
        </Card>

        <Card className="rounded-3xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5 text-indigo-600" />
              Account
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              Resume and job-description data remains scoped to your signed-in account.
            </p>
          </CardContent>
        </Card>
      </div>
    </Shell>
  )
}
