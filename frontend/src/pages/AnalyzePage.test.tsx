import { BrowserRouter } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AnalyzePage } from './AnalyzePage'

const apiMocks = vi.hoisted(() => ({
  resumeList: vi.fn(),
  jobDescriptionList: vi.fn(),
  uploadJobDescription: vi.fn(),
  pasteJobDescription: vi.fn(),
  uploadImages: vi.fn(),
  previewUrl: vi.fn(),
  confirmUrl: vi.fn(),
  uploadResume: vi.fn(),
  jobMatch: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  analysisApi: { jobMatch: apiMocks.jobMatch },
  jobDescriptionApi: {
    list: apiMocks.jobDescriptionList,
    paste: apiMocks.pasteJobDescription,
    upload: apiMocks.uploadJobDescription,
    uploadImages: apiMocks.uploadImages,
    previewUrl: apiMocks.previewUrl,
    confirmUrl: apiMocks.confirmUrl,
  },
  resumeApi: { list: apiMocks.resumeList, upload: apiMocks.uploadResume },
}))

vi.mock('../context/useAuth', () => ({
  useAuth: () => ({ user: { email: 'test@example.com' }, logout: vi.fn() }),
}))

const uploadedJob = {
  id: 7,
  user_id: 1,
  filename: 'senior-engineer.pdf',
  role_name: 'Senior Engineer',
  company_name: 'Example Co',
  source_type: 'upload',
  text_content: 'Extracted responsibilities and required skills.',
  normalized_text: 'Extracted responsibilities and required skills.',
  status: 'ready',
}

function renderAnalyzePage() {
  return render(
    <BrowserRouter>
      <AnalyzePage />
    </BrowserRouter>,
  )
}

describe('AnalyzePage JD document intake', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.resumeList.mockResolvedValue([])
    apiMocks.jobDescriptionList.mockResolvedValue([])
    apiMocks.uploadJobDescription.mockImplementation(async () => {
      apiMocks.jobDescriptionList.mockResolvedValue([uploadedJob])
      return uploadedJob
    })
  })

  it('renders all JD input methods and submits a supported document to the real API client', async () => {
    const user = userEvent.setup()
    renderAnalyzePage()

    const sourceSelect = await screen.findByLabelText('Job description source')
    expect(screen.getByRole('option', { name: 'Paste job description text' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Upload JD document' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Upload JD screenshots' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Import from job URL' })).toBeInTheDocument()

    await user.selectOptions(sourceSelect, 'document')
    const file = new File(['%PDF-1.7 extracted source'], 'senior-engineer.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('JD document file'), file)
    expect(screen.getByText('Selected: senior-engineer.pdf')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Extract JD document' }))

    await waitFor(() => expect(apiMocks.uploadJobDescription).toHaveBeenCalledWith(file))
    expect(await screen.findByText('Extracted responsibilities and required skills.')).toBeInTheDocument()
    expect(screen.getByText(/Processing status: ready/)).toBeInTheDocument()
  })

  it('shows the backend upload failure and does not report success', async () => {
    const user = userEvent.setup()
    apiMocks.uploadJobDescription.mockRejectedValue(new Error('File is empty.'))
    renderAnalyzePage()

    await user.selectOptions(await screen.findByLabelText('Job description source'), 'document')
    const file = new File([], 'empty.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('JD document file'), file)
    await user.click(screen.getByRole('button', { name: 'Extract JD document' }))

    expect(await screen.findByText('File is empty.')).toBeInTheDocument()
    expect(screen.getByText('Selected: empty.pdf')).toBeInTheDocument()
    expect(screen.queryByText('Extracted job description')).not.toBeInTheDocument()
  })
})
