import { useState, useCallback, useEffect } from 'react'

export interface QdrantConfig {
  host: string
  port: number
  apiKey?: string
  collectionName: string
}

export interface ObsidianConfig {
  vaultPath: string
  enabled: boolean
  autoSync: boolean
  syncInterval: number
}

export interface GoogleConfig {
  clientId: string
  clientSecret?: string
  redirectUri: string
  enabled: boolean
  scopes: string[]
  accessToken?: string
  refreshToken?: string
  expiresAt?: number
}

export interface ZimbraConfig {
  enabled: boolean
  email: string
  password: string
  imapHost: string
  imapPort: number
  smtpHost: string
  smtpPort: number
  smtpSsl: boolean
}

export interface AppleCalendarConfig {
  enabled: boolean
  defaultCalendar: string
}

export interface PersonalInfo {
  name: string
  email: string
  timezone: string
  defaultLocation: string
  preferences: {
    temperatureUnit: 'celsius' | 'fahrenheit'
    timeFormat: '12h' | '24h'
    dateFormat: string
  }
}

export interface Settings {
  qdrant: QdrantConfig
  obsidian: ObsidianConfig
  google: GoogleConfig
  zimbra: ZimbraConfig
  appleCalendar: AppleCalendarConfig
  personal: PersonalInfo
  theme: 'dark' | 'light' | 'auto'
  voice: {
    enabled: boolean
    wakeWord: string
    sensitivity: number
  }
}

const defaultSettings: Settings = {
  qdrant: {
    host: 'localhost',
    port: 6333,
    collectionName: 'jarvis_knowledge'
  },
  obsidian: {
    vaultPath: '',
    enabled: false,
    autoSync: true,
    syncInterval: 60
  },
  google: {
    clientId: '',
    redirectUri: 'http://localhost:8001/auth/callback',
    enabled: false,
    scopes: [
      'https://www.googleapis.com/auth/gmail.modify',
      'https://www.googleapis.com/auth/calendar'
    ]
  },
  zimbra: {
    enabled: false,
    email: '',
    password: '',
    imapHost: 'ssl0.ovh.net',
    imapPort: 993,
    smtpHost: 'ssl0.ovh.net',
    smtpPort: 465,
    smtpSsl: true
  },
  appleCalendar: {
    enabled: false,
    defaultCalendar: ''
  },
  personal: {
    name: '',
    email: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    defaultLocation: '',
    preferences: {
      temperatureUnit: 'celsius',
      timeFormat: '24h',
      dateFormat: 'DD/MM/YYYY'
    }
  },
  theme: 'dark',
  voice: {
    enabled: true,
    wakeWord: 'Hey JARVIS',
    sensitivity: 0.5
  }
}

const STORAGE_KEY = 'jarvis_settings'

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? { ...defaultSettings, ...JSON.parse(stored) } : defaultSettings
  })
  
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const API_BASE_URL = 'http://localhost:8001'

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
    fetch(`${API_BASE_URL}/api/settings/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    }).catch(() => {})
  }, [settings])

  const updateQdrant = useCallback((config: Partial<QdrantConfig>) => {
    setSettings(prev => ({
      ...prev,
      qdrant: { ...prev.qdrant, ...config }
    }))
  }, [])

  const updateObsidian = useCallback((config: Partial<ObsidianConfig>) => {
    setSettings(prev => ({
      ...prev,
      obsidian: { ...prev.obsidian, ...config }
    }))
  }, [])

  const updateGoogle = useCallback((config: Partial<GoogleConfig>) => {
    setSettings(prev => ({
      ...prev,
      google: { ...prev.google, ...config }
    }))
  }, [])

  const updateZimbra = useCallback((config: Partial<ZimbraConfig>) => {
    setSettings(prev => ({
      ...prev,
      zimbra: { ...prev.zimbra, ...config }
    }))
  }, [])

  const updateAppleCalendar = useCallback((config: Partial<AppleCalendarConfig>) => {
    setSettings(prev => ({
      ...prev,
      appleCalendar: { ...prev.appleCalendar, ...config }
    }))
  }, [])

  const updatePersonal = useCallback((info: Partial<PersonalInfo>) => {
    setSettings(prev => ({
      ...prev,
      personal: { ...prev.personal, ...info }
    }))
  }, [])

  const updateVoice = useCallback((config: Partial<Settings['voice']>) => {
    setSettings(prev => ({
      ...prev,
      voice: { ...prev.voice, ...config }
    }))
  }, [])

  const setTheme = useCallback((theme: Settings['theme']) => {
    setSettings(prev => ({ ...prev, theme }))
  }, [])

  const testQdrantConnection = useCallback(async (): Promise<boolean> => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE_URL}/api/qdrant/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: settings.qdrant.host,
          port: settings.qdrant.port,
          collection: settings.qdrant.collectionName
        })
      })
      setIsLoading(false)
      const data = await response.json()
      return data.connected || false
    } catch (err) {
      setIsLoading(false)
      setError(err instanceof Error ? err.message : 'Failed to connect to Qdrant')
      return false
    }
  }, [settings.qdrant])

  const bootstrapQdrant = useCallback(async (): Promise<boolean> => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await fetch(
        `http://${settings.qdrant.host}:${settings.qdrant.port}/collections/${settings.qdrant.collectionName}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            ...(settings.qdrant.apiKey && { 'api-key': settings.qdrant.apiKey })
          },
          body: JSON.stringify({
            vectors: {
              size: 1536,
              distance: 'Cosine'
            }
          })
        }
      )
      setIsLoading(false)
      return response.ok
    } catch (err) {
      setIsLoading(false)
      setError(err instanceof Error ? err.message : 'Failed to bootstrap Qdrant')
      return false
    }
  }, [settings.qdrant])

  const testObsidianConnection = useCallback(async (): Promise<boolean> => {
    if (!settings.obsidian.vaultPath) return false
    return true
  }, [settings.obsidian])

  const syncObsidian = useCallback(async (): Promise<{success: boolean, totalFiles?: number, indexed?: number, qdrantStatus?: string} | null> => {
    console.log('📝 Obsidian sync initiated from frontend')
    console.log('📁 Vault path:', settings.obsidian.vaultPath)
    console.log('🌐 API URL:', `${API_BASE_URL}/api/obsidian/sync`)
    
    setIsLoading(true)
    setError(null)
    
    try {
      console.log('📤 Sending POST request...')
      const response = await fetch(`${API_BASE_URL}/api/obsidian/sync`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ vaultPath: settings.obsidian.vaultPath })
      })
      
      console.log('📥 Response received:', response.status, response.statusText)
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error('❌ Obsidian sync failed:', errorText)
        setError(`Sync failed: ${response.status} ${response.statusText}`)
        setIsLoading(false)
        return null
      }
      
      const data = await response.json()
      console.log('✅ Obsidian sync response:', data)
      setIsLoading(false)
      return data
    } catch (err) {
      console.error('❌ Obsidian sync error:', err)
      setIsLoading(false)
      setError(err instanceof Error ? err.message : 'Failed to sync Obsidian')
      return null
    }
  }, [settings.obsidian.vaultPath])

  const initiateGoogleAuth = useCallback(() => {
    if (!settings.google.clientId) return
    
    const params = new URLSearchParams({
      client_id: settings.google.clientId,
      redirect_uri: settings.google.redirectUri,
      response_type: 'code',
      scope: settings.google.scopes.join(' '),
      access_type: 'offline',
      prompt: 'consent'
    })
    
    window.open(
      `https://accounts.google.com/o/oauth2/v2/auth?${params}`,
      '_blank',
      'width=500,height=600'
    )
  }, [settings.google])

  const disconnectGoogle = useCallback(() => {
    updateGoogle({
      accessToken: undefined,
      refreshToken: undefined,
      expiresAt: undefined,
      enabled: false
    })
  }, [updateGoogle])

  const checkGoogleConnection = useCallback(async (): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/google/status`)
      if (response.ok) {
        const data = await response.json()
        if (data.connected && !settings.google.enabled) {
          updateGoogle({ enabled: true })
        }
        return data.connected
      }
      return false
    } catch (err) {
      return false
    }
  }, [settings.google.enabled, updateGoogle])

  const checkQdrantStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/qdrant/status`)
      if (response.ok) {
        return await response.json()
      }
      return null
    } catch (err) {
      return null
    }
  }, [])

  const testZimbraConnection = useCallback(async (): Promise<{ok: boolean, error?: string}> => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE_URL}/api/zimbra/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings.zimbra)
      })
      setIsLoading(false)
      const data = await response.json()
      return { ok: !!data.ok, error: data.error }
    } catch (err) {
      setIsLoading(false)
      const msg = err instanceof Error ? err.message : 'Failed to test Zimbra connection'
      setError(msg)
      return { ok: false, error: msg }
    }
  }, [settings.zimbra])

  const checkZimbraStatus = useCallback(async (): Promise<{configured: boolean, lastTested?: number, ok?: boolean} | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/zimbra/status`)
      if (response.ok) {
        return await response.json()
      }
      return null
    } catch (err) {
      return null
    }
  }, [])

  const testAppleCalendar = useCallback(async (): Promise<{ok: boolean, error?: string}> => {
    setIsLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE_URL}/api/apple_calendar/test`, { method: 'POST' })
      setIsLoading(false)
      const data = await response.json()
      return { ok: !!data.ok, error: data.error }
    } catch (err) {
      setIsLoading(false)
      const msg = err instanceof Error ? err.message : 'Failed to probe Apple Calendar'
      setError(msg)
      return { ok: false, error: msg }
    }
  }, [])

  const checkAppleCalendarStatus = useCallback(async (): Promise<{enabled: boolean, available: boolean, lastTested?: number, ok?: boolean} | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/apple_calendar/status`)
      if (response.ok) return await response.json()
      return null
    } catch {
      return null
    }
  }, [])

  const listAppleCalendars = useCallback(async (): Promise<string[]> => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/apple_calendar/calendars`)
      if (!response.ok) return []
      const data = await response.json()
      return Array.isArray(data.calendars) ? data.calendars : []
    } catch {
      return []
    }
  }, [])

  const checkObsidianStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/obsidian/status`)
      if (response.ok) {
        return await response.json()
      }
      return null
    } catch (err) {
      return null
    }
  }, [])

  const saveSettings = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/settings/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      })
      return response.ok
    } catch (err) {
      return false
    }
  }, [settings])

  const loadSettings = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/settings/load`)
      if (response.ok) {
        const data = await response.json()
        if (data && Object.keys(data).length > 0) {
          setSettings(prev => ({ ...prev, ...data }))
        }
        return data
      }
      return null
    } catch (err) {
      return null
    }
  }, [])

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  return {
    settings,
    isLoading,
    error,
    updateQdrant,
    updateObsidian,
    updateGoogle,
    updateZimbra,
    updatePersonal,
    updateVoice,
    setTheme,
    testQdrantConnection,
    bootstrapQdrant,
    testObsidianConnection,
    syncObsidian,
    initiateGoogleAuth,
    disconnectGoogle,
    checkGoogleConnection,
    testZimbraConnection,
    checkZimbraStatus,
    updateAppleCalendar,
    testAppleCalendar,
    checkAppleCalendarStatus,
    listAppleCalendars,
    checkQdrantStatus,
    checkObsidianStatus,
    saveSettings,
    loadSettings,
    clearError: () => setError(null)
  }
}

export default useSettings
