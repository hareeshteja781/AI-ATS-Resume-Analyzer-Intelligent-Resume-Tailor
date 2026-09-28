import { useEffect, useMemo, useState } from 'react'
import { authApi } from '../lib/api'
import type { User } from '../types'
import { AuthContext, type AuthContextValue } from './auth-context'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('ats_token')
    if (!token) {
      const frame = requestAnimationFrame(() => setIsLoading(false))
      return () => cancelAnimationFrame(frame)
    }

    authApi
      .me()
      .then((payload) => setUser(payload))
      .catch(() => {
        localStorage.removeItem('ats_token')
        setUser(null)
      })
      .finally(() => {
        const frame = requestAnimationFrame(() => setIsLoading(false))
        return () => cancelAnimationFrame(frame)
      })
  }, [])

  const login = async (email: string, password: string) => {
    const data = await authApi.login(email, password)
    localStorage.setItem('ats_token', data.access_token)
    const currentUser = await authApi.me()
    setUser(currentUser)
  }

  // TEMPORARY LOCAL-DEVELOPMENT TEST LOGIN — remove before public deployment.
  const devTestLogin = async () => {
    const data = await authApi.devTestLogin()
    localStorage.setItem('ats_token', data.access_token)
    const currentUser = await authApi.me()
    setUser(currentUser)
  }

  const register = async (email: string, password: string) => {
    const data = await authApi.register(email, password)
    if (!data.access_token) {
      const loggedIn = await authApi.login(email, password)
      localStorage.setItem('ats_token', loggedIn.access_token)
    } else {
      localStorage.setItem('ats_token', data.access_token)
    }
    const currentUser = await authApi.me()
    setUser(currentUser)
  }

  const logout = () => {
    localStorage.removeItem('ats_token')
    setUser(null)
  }

  const value = useMemo<AuthContextValue>(
    () => ({ user, isAuthenticated: Boolean(user), isLoading, login, devTestLogin, register, logout }),
    [user, isLoading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
