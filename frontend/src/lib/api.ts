export type ApiError = {
  detail?: string | { message?: string }
  message?: string
}

const API_BASE = (import.meta.env.VITE_API_URL ?? '/api/v1').replace(/\/+$/, '')

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('ats_token')

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  })

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('content-type') ?? ''
  const payload = contentType.includes('application/json') ? await response.json() : await response.text()

  if (!response.ok) {
    const message =
      typeof payload === 'string'
        ? payload
        : payload?.detail ?? payload?.message ?? 'Request failed'
    throw new Error(typeof message === 'string' ? message : 'Request failed')
  }

  return payload as T
}

async function requestBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const token = localStorage.getItem('ats_token')
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  })

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? ''
    const payload = contentType.includes('application/json') ? await response.json() : await response.text()
    const message = typeof payload === 'string' ? payload : payload?.detail ?? 'Document preview failed'
    throw new Error(typeof message === 'string' ? message : 'Document preview failed')
  }

  return response.blob()
}

async function download(path: string): Promise<{ blob: Blob; filename: string }> {
  const token = localStorage.getItem('ats_token')
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? ''
    const payload = contentType.includes('application/json') ? await response.json() : await response.text()
    const message = typeof payload === 'string' ? payload : payload?.detail ?? 'Download failed'
    throw new Error(typeof message === 'string' ? message : 'Download failed')
  }

  const disposition = response.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename="([^"]+)"/i)
  return { blob: await response.blob(), filename: match?.[1] ?? 'resume-download' }
}

export type SaveFileHandle = {
  createWritable: () => Promise<{
    write: (data: Blob) => Promise<void>
    close: () => Promise<void>
  }>
}

type FilePickerWindow = Window & {
  showSaveFilePicker?: (options?: {
    suggestedName?: string
    types?: Array<{
      description?: string
      accept: Record<string, string[]>
    }>
  }) => Promise<SaveFileHandle>
}

function sanitizeDownloadFilename(filename: string) {
  return filename.replace(/[<>:"/\\|?*]/g, '_').trim() || 'resume-download'
}

function saveBlobFallback(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = sanitizeDownloadFilename(filename)
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function pickSaveFile(
  suggestedFilename: string,
  description: string,
  mimeType: string,
  extension: string,
): Promise<SaveFileHandle | null> {
  const pickerWindow = window as FilePickerWindow
  if (!pickerWindow.showSaveFilePicker) return null

  try {
    return await pickerWindow.showSaveFilePicker({
      suggestedName: sanitizeDownloadFilename(suggestedFilename),
      types: [{ description, accept: { [mimeType]: [extension] } }],
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') return null
    throw error
  }
}

export async function downloadToSaveFile(path: string, handle: SaveFileHandle) {
  const result = await download(path)
  const writable = await handle.createWritable()
  await writable.write(result.blob)
  await writable.close()
  return result
}

async function downloadToFile(
  path: string,
  suggestedFilename: string,
  description: string,
  mimeType: string,
  extension: string,
) {
  const handle = await pickSaveFile(suggestedFilename, description, mimeType, extension)
  if (handle) {
    await downloadToSaveFile(path, handle)
    return
  }

  const result = await download(path)
  saveBlobFallback(result.blob, result.filename || suggestedFilename)
}

export const authApi = {
  register: (email: string, password: string) =>
    request<{ id: number; email: string; is_active: boolean; access_token?: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  // TEMPORARY LOCAL-DEVELOPMENT TEST LOGIN — remove before public deployment.
  devTestLogin: () =>
    request<{ access_token: string; token_type: string }>('/auth/dev-test-login', {
      method: 'POST',
    }),
  me: () => request<{ id: number; email: string; is_active: boolean }>('/auth/me'),
}

export const resumeApi = {
  list: () =>
    request<Array<{ id: number; user_id: number; filename: string; original_filename: string; content_type?: string; text_content: string; status: string; storage_path: string; processing_error?: string | null; docx_layout_preserved?: boolean }>>('/resumes'),
  preview: (resumeId: number) => requestBlob(`/resumes/${resumeId}/preview`),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return request<{ id: number; user_id: number; filename: string; original_filename: string; text_content: string; status: string; storage_path: string; processing_error?: string | null; docx_layout_preserved?: boolean }>(
      '/resumes/upload',
      { method: 'POST', body: formData },
    )
  },
  delete: (resumeId: number) =>
    request<void>('/resumes/' + resumeId, { method: 'DELETE' }),
}

export const jobDescriptionApi = {
  list: () =>
    request<Array<{ id: number; user_id: number; filename?: string | null; role_name?: string | null; company_name?: string | null; source_type: string; text_content: string; normalized_text: string; source_html?: string | null; status: string; url?: string | null; processing_error?: string | null; storage_path?: string | null }>>('/job-descriptions'),
  paste: (text: string) =>
    request<{ id: number; user_id: number; role_name?: string | null; company_name?: string | null; text_content: string; normalized_text: string; source_html?: string | null; status: string }>('/job-descriptions/paste', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return request<{ id: number; user_id: number; text_content: string; normalized_text: string; status: string; storage_path?: string | null }>('/job-descriptions/upload', {
      method: 'POST',
      body: formData,
    })
  },
  uploadImages: (files: File[]) => {
    const formData = new FormData()
    files.forEach((file) => formData.append('files', file))
    return request<{
      id: number
      user_id: number
      role_name?: string | null
      company_name?: string | null
      text_content: string
      normalized_text: string
      status: string
      source_images: Array<{ filename: string; content_type: string; width: number; height: number }>
      structured_extraction: Record<string, unknown>
    }>('/job-descriptions/images', { method: 'POST', body: formData })
  },
  fromUrl: (url: string) =>
    request<{ source_url: string; final_url: string; role_name?: string | null; company_name?: string | null; text_content: string; normalized_text: string; structured_extraction: Record<string, unknown> }>('/job-descriptions/url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  previewUrl: (url: string) =>
    request<{ source_url: string; final_url: string; role_name?: string | null; company_name?: string | null; text_content: string; normalized_text: string; structured_extraction: Record<string, unknown> }>('/job-descriptions/url/preview', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  confirmUrl: (url: string, text: string) =>
    request<{ id: number; user_id: number; role_name?: string | null; company_name?: string | null; source_type: string; text_content: string; normalized_text: string; status: string }>('/job-descriptions/url/confirm', {
      method: 'POST',
      body: JSON.stringify({ url, text }),
    }),
}

export const analysisApi = {
  jobMatch: (resumeId: number, jobDescriptionId: number) =>
    request<{
      id: number
      user_id: number
      resume_id: number
      job_description_id: number
      job_match_score: number
      ats_compatibility_score: number
      layout_preservation_score: number
      truthfulness_status: string
      matched_skills: string[]
      missing_skills: string[]
      partially_matched_skills: string[]
      responsibilities_matched: string[]
      evidence_found: string[]
      important_gaps: string[]
      ats_structure_issues: string[]
      recommendations: string[]
      score_breakdown: Record<string, number>
      benchmark: Record<string, unknown>
      requirement_matches?: Array<Record<string, unknown>>
      section_scores: Record<string, number>
      section_details: Record<string, string[]>
      present_sections?: string[]
      project_matches: Array<Record<string, unknown>>
      layout_analysis: Record<string, unknown>
    }>('/analysis/job-match', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, job_description_id: jobDescriptionId }),
    }),
  jobMatchAsync: (resumeId: number, jobDescriptionId: number) =>
    request<{ task_id: number; status: string; progress: number; result: Record<string, unknown> | null }>('/analysis/job-match/async', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, job_description_id: jobDescriptionId }),
    }),
}

export const taskApi = {
  get: (taskId: number) =>
    request<{ id: number; status: string; progress: number; retryable: boolean; error_message: string | null; result: Record<string, unknown> | null }>(`/tasks/${taskId}`),
}

export const tailoringApi = {
  preview: (resumeId: number, jobDescriptionId: number) =>
    request<{ original_text: string; modified_text: string | null; modifications: Array<Record<string, unknown>>; auto_applied_change_ids?: string[]; available_keywords?: Array<Record<string, unknown>>; diff: Array<Record<string, string>>; validation_errors: string[] }>('/tailoring/preview', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, job_description_id: jobDescriptionId }),
    }),
  documentPreview: (resumeId: number, jobDescriptionId: number, format: 'docx' | 'pdf', acceptedChangeIds: string[] = []) =>
    requestBlob('/tailoring/document-preview', {
      method: 'POST',
      body: JSON.stringify({
        resume_id: resumeId,
        job_description_id: jobDescriptionId,
        accepted_change_ids: acceptedChangeIds,
        format,
      }),
    }),
  finalizeText: (resumeId: number, jobDescriptionId: number, acceptedChangeIds: string[]) =>
    request<{ resume_id: number; job_description_id: number; original_text: string; final_text: string; accepted_changes: Array<Record<string, unknown>>; validation_errors: string[] }>('/tailoring/finalize', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, job_description_id: jobDescriptionId, accepted_change_ids: acceptedChangeIds }),
    }),
  decide: (modificationId: string, accepted?: boolean, userVerified?: boolean) =>
    request<{ id: string; accepted: boolean; decision: string; user_verified: boolean; truthfulness_status: string }>(`/tailoring/changes/${modificationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ accepted, user_verified: userVerified }),
    }),
  finalize: (resumeId: number, jobDescriptionId: number, acceptedChangeIds: string[]) =>
    request<{ resume_id: number; job_description_id: number; original_text: string; final_text: string; accepted_changes: Array<Record<string, unknown>>; validation_errors: string[] }>('/tailoring/finalize', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, job_description_id: jobDescriptionId, accepted_change_ids: acceptedChangeIds }),
    }),
}

export const versionApi = {
  history: (query = '') =>
    request<Array<Record<string, unknown>>>(`/resume-versions/history${query ? `?q=${encodeURIComponent(query)}` : ''}`),
  previewPdf: async (versionId: number) => {
    const token = localStorage.getItem('ats_token')
    const response = await fetch(`${API_BASE}/resume-versions/${versionId}/preview/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) throw new Error('Resume preview could not be loaded')
    return URL.createObjectURL(await response.blob())
  },
  list: (resumeId: number) =>
    request<Array<Record<string, unknown>>>(`/resume-versions/resume/${resumeId}`),
  delete: (versionId: number) =>
    request<{ id: number; message: string }>(`/resume-versions/${versionId}`, {
      method: 'DELETE',
    }),
  createTailored: (resumeId: number, jobDescriptionId: number, versionName = 'tailored version', acceptedChangeIds: string[] = []) =>
    request<Record<string, unknown>>('/resume-versions/tailored', {
      method: 'POST',
      body: JSON.stringify({
        resume_id: resumeId,
        job_description_id: jobDescriptionId,
        version_name: versionName,
        accepted_change_ids: acceptedChangeIds,
      }),
    }),
  compare: (baseVersionId: number, targetVersionId: number) =>
    request<{ base_version_id: number; target_version_id: number; base_version_name: string; target_version_name: string; base_text: string; target_text: string; diff: Array<Record<string, string>>; validation_errors: string[] }>('/resume-versions/compare', {
      method: 'POST',
      body: JSON.stringify({ base_version_id: baseVersionId, target_version_id: targetVersionId }),
    }),
  restore: (resumeId: number, versionId: number) =>
    request<{ resume_id: number; restored_version_id: number; restored_text: string; message: string }>('/resume-versions/restore', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, version_id: versionId }),
    }),
  finalize: (versionId: number, resumeId: number) =>
    request<Record<string, unknown>>('/resume-versions/finalize', {
      method: 'POST',
      body: JSON.stringify({ resume_id: resumeId, version_id: versionId }),
    }),
  downloadDocx: async (versionId: number, suggestedFilename = 'resume.docx') => {
    await downloadToFile(
      `/resume-versions/${versionId}/download/docx`,
      suggestedFilename,
      'Microsoft Word document',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      '.docx',
    )
  },
  downloadPdf: async (versionId: number, suggestedFilename = 'resume.pdf') => {
    await downloadToFile(
      `/resume-versions/${versionId}/download/pdf`,
      suggestedFilename,
      'PDF document',
      'application/pdf',
      '.pdf',
    )
  },
}
