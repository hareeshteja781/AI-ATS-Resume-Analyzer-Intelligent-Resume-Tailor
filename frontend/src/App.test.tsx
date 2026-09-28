import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders the auth screen by default', async () => {
    render(<App />)
    expect(await screen.findByText(/sign in/i)).toBeInTheDocument()
  })
})
