import { beforeEach, describe, expect, it, vi } from 'vitest'
import { jobDescriptionApi } from './api'

describe('jobDescriptionApi.upload', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('posts the JD document as multipart form data to the upload endpoint', async () => {
    const responsePayload = {
      id: 7,
      user_id: 1,
      text_content: 'Extracted JD text',
      normalized_text: 'Extracted JD text',
      status: 'ready',
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(responsePayload), {
      status: 201,
      headers: { 'content-type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['%PDF-1.7'], 'role.pdf', { type: 'application/pdf' })

    await expect(jobDescriptionApi.upload(file)).resolves.toEqual(responsePayload)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/job-descriptions/upload', expect.objectContaining({ method: 'POST' }))
    const request = fetchMock.mock.calls[0][1] as RequestInit
    expect(request.body).toBeInstanceOf(FormData)
    expect((request.body as FormData).get('file')).toBe(file)
  })
})
