import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Trash2 } from 'lucide-react'

export type ResumeOption = {
  id?: unknown
  original_filename?: unknown
  filename?: unknown
}

type ResumeSelectorProps = {
  resumes: ResumeOption[]
  value: number | null
  onChange: (id: number | null) => void
  onDelete: (resumeId: number) => void
  disabled?: boolean
  dark?: boolean
}

const resumeName = (resume: ResumeOption) =>
  String(resume.original_filename ?? resume.filename ?? 'Resume')

export function ResumeSelector({
  resumes,
  value,
  onChange,
  onDelete,
  disabled = false,
  dark = false,
}: ResumeSelectorProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }

    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [open])

  const selected = resumes.find((resume) => Number(resume.id) === value)
  const triggerClass = dark
    ? 'border-slate-700 bg-slate-950 text-slate-100'
    : 'border-slate-200 bg-white text-slate-900'
  const menuClass = dark
    ? 'border-slate-700 bg-slate-950 text-slate-100'
    : 'border-slate-200 bg-white text-slate-900'
  return (
    <div ref={rootRef} className="relative w-full">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className={`flex w-full items-center justify-between rounded-xl border px-3 py-2.5 text-left outline-none transition focus:border-indigo-400 disabled:cursor-not-allowed disabled:opacity-60 ${triggerClass}`}
      >
        <span className={selected ? '' : 'text-slate-400'}>
          {selected ? resumeName(selected) : 'Choose a saved resume'}
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open ? (
        <div
          role="listbox"
          className={`absolute left-0 right-0 top-full z-50 mt-2 max-h-72 overflow-y-auto rounded-xl border p-1 shadow-2xl ${menuClass}`}
        >
          {resumes.length ? (
            resumes.map((resume) => {
              const selectedRow = Number(resume.id) === value
              return (
                <div
                  key={String(resume.id)}
                  role="option"
                  aria-selected={selectedRow}
                  className={`flex items-center gap-1 rounded-lg ${selectedRow ? 'bg-indigo-50 dark:bg-indigo-950/40' : 'hover:bg-slate-100 dark:hover:bg-slate-900'}`}
                >
                  <button
                    type="button"
                    onClick={() => {
                      onChange(Number(resume.id))
                      setOpen(false)
                    }}
                    className="min-w-0 flex-1 px-3 py-2.5 text-left text-sm"
                  >
                    <span className="block truncate">{resumeName(resume)}</span>
                    {selectedRow ? <Check className="mr-1 inline h-3.5 w-3.5 text-indigo-600" /> : null}
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${resumeName(resume)}`}
                    title="Permanently delete this resume"
                    onClick={() => onDelete(Number(resume.id))}
                    className="mr-1 rounded-md p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              )
            })
          ) : (
            <div className="px-3 py-3 text-sm text-slate-400">No saved resumes</div>
          )}
        </div>
      ) : null}
    </div>
  )
}
