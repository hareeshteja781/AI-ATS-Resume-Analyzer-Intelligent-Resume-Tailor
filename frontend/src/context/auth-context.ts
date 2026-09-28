import { createContext } from 'react'
import type { User } from '../types'

export type AuthContextValue = {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  // TEMPORARY LOCAL-DEVELOPMENT TEST LOGIN — remove before public deployment.
  devTestLogin: () => Promise<void>
  register: (email: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
