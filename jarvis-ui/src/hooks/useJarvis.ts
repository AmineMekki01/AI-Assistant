import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useWebSocket } from './useWebSocket'
import { useAudio } from './useAudio'
import type { JarvisState, JarvisActions, SystemMetrics, MailDraft } from '../types'
import type { Settings } from './useSettings'

interface VoiceSettings {
  enabled: boolean
  wakeWord: string
  sensitivity: number
}

const DEFAULT_VOICE_SETTINGS: VoiceSettings = {
  enabled: true,
  wakeWord: 'Hey JARVIS',
  sensitivity: 0.5
}

function readVoiceSettingsFromStorage(): VoiceSettings {
  if (typeof window === 'undefined') {
    return DEFAULT_VOICE_SETTINGS
  }

  try {
    const stored = localStorage.getItem('jarvis_settings')
    if (!stored) {
      return DEFAULT_VOICE_SETTINGS
    }

    const parsed = JSON.parse(stored) as { voice?: Partial<VoiceSettings> }
    const voice = parsed.voice ?? {}

    return {
      enabled: typeof voice.enabled === 'boolean' ? voice.enabled : DEFAULT_VOICE_SETTINGS.enabled,
      wakeWord: typeof voice.wakeWord === 'string' && voice.wakeWord.trim() ? voice.wakeWord.trim() : DEFAULT_VOICE_SETTINGS.wakeWord,
      sensitivity: typeof voice.sensitivity === 'number' ? voice.sensitivity : DEFAULT_VOICE_SETTINGS.sensitivity
    }
  } catch {
    return DEFAULT_VOICE_SETTINGS
  }
}

function inferRecipientFromTranscript(text: string): string {
  const emailMatch = text.match(/\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b/)
  if (emailMatch) {
    return `${emailMatch[1]}@${emailMatch[2]}`
  }

  const spacedEmailMatch = text.match(/\b((?:[A-Za-z0-9]\s+)+[A-Za-z0-9](?:\s*\.\s*[A-Za-z0-9]+)?)\s+(?:at|@)\s+([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b/i)
  if (spacedEmailMatch) {
    return `${spacedEmailMatch[1].replace(/\s+/g, '')}@${spacedEmailMatch[2].toLowerCase()}`
  }

  const gmailMatch = text.match(/\b([A-Za-z0-9._%+-]+)\.?gmail\.com\b/i)
  if (gmailMatch) {
    return `${gmailMatch[1]}@gmail.com`
  }

  const atGmailMatch = text.match(/\b([A-Za-z0-9._%+-]+)\s+(?:at|@)\s+gmail\.com\b/i)
  if (atGmailMatch) {
    return `${atGmailMatch[1]}@gmail.com`
  }

  return 'recipient not captured'
}

function parseMailDraftFromTranscript(assistantText: string, userText: string): MailDraft | null {
  const normalizedText = assistantText.toLowerCase()
  if (!normalizedText.includes('subject:') || !normalizedText.includes('body:')) {
    return null
  }

  const subjectMatch = assistantText.match(/Subject:\s*([\s\S]*?)(?:\n\s*Body:|\n\s*$)/i)
  const bodyMatch = assistantText.match(/Body:\s*([\s\S]*?)(?:\n\s*\n(?:Shall I send it\?|Would you like me to send|Does this look correct\?|Would you like)|$)/i)

  if (!subjectMatch || !bodyMatch) {
    return null
  }

  const body = bodyMatch[1]
    .split('\n')
    .map(line => line.replace(/^\s+/, '').replace(/\s+$/, ''))
    .join('\n')
    .trim()

  const subject = subjectMatch[1]
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .join(' ')
    .replace(/\s+(?:Would you like.*|Shall I send it\?.*|Does this look correct\?.*|Would you like me to send.*)$/i, '')
    .trim()

  return {
    account: 'gmail',
    to: inferRecipientFromTranscript(userText),
    subject,
    body,
    rawText: assistantText
  }
}

export function useJarvis(): { state: JarvisState; actions: JarvisActions } {
  const [currentTime, setCurrentTime] = useState(new Date())
  const [uiRecording, setUiRecording] = useState(false)
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null)
  const [pendingMailDraft, setPendingMailDraft] = useState<MailDraft | null>(null)
  const [voiceSettings, setVoiceSettings] = useState<VoiceSettings>(readVoiceSettingsFromStorage)
  const [isWakeListening, setIsWakeListening] = useState(false)

  const isRecordingRef = useRef(false)
  const isSpeakingRef = useRef(false)
  const dismissedMailDraftRef = useRef<string | null>(null)
  const voiceSettingsRef = useRef<VoiceSettings>(voiceSettings)

  const {
    connectionState,
    statusMessage,
    messages,
    isRecording: wsIsRecording,
    isSpeaking,
    toggleRecording,
    sendAudioChunk,
    send,
    pendingMailDraft: backendMailDraft
  } = useWebSocket('ws://localhost:8000/ws')

  const refreshSystemMetrics = useCallback(async () => {
    const startedAt = performance.now()
    try {
      const response = await fetch('http://localhost:8001/api/system/metrics')
      if (!response.ok) {
        setSystemMetrics(prev => prev ? { ...prev, latencyMs: Math.round(performance.now() - startedAt), status: 'error' } : null)
        return
      }

      const data = await response.json() as Omit<SystemMetrics, 'latencyMs'>
      setSystemMetrics({
        ...data,
        latencyMs: Math.round(performance.now() - startedAt)
      })
    } catch {
      setSystemMetrics(prev => prev ? { ...prev, latencyMs: Math.round(performance.now() - startedAt), status: 'error' } : null)
    }
  }, [])

  useEffect(() => {
    isSpeakingRef.current = isSpeaking
  }, [isSpeaking])

  useEffect(() => {
    voiceSettingsRef.current = voiceSettings
  }, [voiceSettings])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    const handleSettingsUpdate = (event: Event) => {
      const detail = (event as CustomEvent<Settings>).detail
      if (!detail?.voice) {
        return
      }

      setVoiceSettings(prev => ({
        enabled: typeof detail.voice.enabled === 'boolean' ? detail.voice.enabled : prev.enabled,
        wakeWord: typeof detail.voice.wakeWord === 'string' && detail.voice.wakeWord.trim() ? detail.voice.wakeWord.trim() : prev.wakeWord,
        sensitivity: typeof detail.voice.sensitivity === 'number' ? detail.voice.sensitivity : prev.sensitivity
      }))
    }

    window.addEventListener('jarvis-settings-updated', handleSettingsUpdate as EventListener)
    return () => window.removeEventListener('jarvis-settings-updated', handleSettingsUpdate as EventListener)
  }, [])

  useEffect(() => {
    if (wsIsRecording !== isRecordingRef.current) {
      isRecordingRef.current = wsIsRecording
      setUiRecording(wsIsRecording)
    }
  }, [wsIsRecording])

  const chunkCounter = useRef(0)
  const { startRecording, stopRecording, audioLevel } = useAudio(
    useCallback((data: Float32Array) => {
      chunkCounter.current++
      if (chunkCounter.current <= 3) {
        console.log(`🎤 Audio chunk #${chunkCounter.current}:`, data.length, 'samples')
      }

      if (isRecordingRef.current && !isSpeakingRef.current) {
        sendAudioChunk(data)
      }
    }, [sendAudioChunk])
  )

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    refreshSystemMetrics()
    const timer = setInterval(refreshSystemMetrics, 60000)
    return () => clearInterval(timer)
  }, [refreshSystemMetrics])

  useEffect(() => {
    if (!backendMailDraft) {
      return
    }

    if (dismissedMailDraftRef.current === backendMailDraft.rawText) {
      return
    }

    setPendingMailDraft(prev => prev?.rawText === backendMailDraft.rawText ? prev : backendMailDraft)
  }, [backendMailDraft])

  useEffect(() => {
    if (backendMailDraft || pendingMailDraft) {
      return
    }

    const latestAssistantMessage = [...messages].reverse().find(message => message.role === 'assistant')
    const latestUserMessage = [...messages].reverse().find(message => message.role === 'user')
    if (!latestAssistantMessage || !latestUserMessage) {
      return
    }

    const parsedDraft = parseMailDraftFromTranscript(latestAssistantMessage.text, latestUserMessage.text)
    if (!parsedDraft || dismissedMailDraftRef.current === parsedDraft.rawText) {
      return
    }

    setPendingMailDraft(prev => prev?.rawText === parsedDraft.rawText ? prev : parsedDraft)
  }, [backendMailDraft, messages, pendingMailDraft])

  const clearPendingMailDraft = useCallback(() => {
    if (pendingMailDraft) {
      dismissedMailDraftRef.current = pendingMailDraft.rawText
    }
    setPendingMailDraft(null)
  }, [pendingMailDraft])

  const updateMailDraftField = useCallback((field: 'to' | 'subject' | 'body', value: string) => {
    setPendingMailDraft(prev => prev ? { ...prev, [field]: value } : prev)
  }, [])

  const confirmMailDraft = useCallback(() => {
    if (!pendingMailDraft) {
      return
    }

    clearPendingMailDraft()
    send({ type: 'confirm_mail_draft', accepted: true, draft: pendingMailDraft })
  }, [clearPendingMailDraft, pendingMailDraft, send])

  const cancelMailDraft = useCallback(() => {
    if (!pendingMailDraft) {
      return
    }

    clearPendingMailDraft()
    send({ type: 'confirm_mail_draft', accepted: false, draft: pendingMailDraft })
  }, [clearPendingMailDraft, pendingMailDraft, send])

  useEffect(() => {
    if (!pendingMailDraft) {
      return
    }

    const latestUserMessage = [...messages].reverse().find(message => message.role === 'user')
    if (!latestUserMessage) {
      return
    }

    const normalized = latestUserMessage.text.trim().toLowerCase()
    const affirmative = ['yes', 'yep', 'yeah', 'send it', 'confirm', 'do it', 'please send it']
    const negative = ['no', 'nope', 'cancel', 'don\'t send', 'do not send', 'stop']

    if (affirmative.includes(normalized) || negative.includes(normalized)) {
      if (affirmative.includes(normalized)) {
        confirmMailDraft()
      } else {
        cancelMailDraft()
      }
    }
  }, [cancelMailDraft, confirmMailDraft, messages, pendingMailDraft])

  const handleToggleRecording = useCallback(() => {
    const newState = !isRecordingRef.current
    isRecordingRef.current = newState
    setUiRecording(newState)

    if (newState) {
      chunkCounter.current = 0
      startRecording()
    } else {
      stopRecording()
    }
    toggleRecording()
  }, [startRecording, stopRecording, toggleRecording])

  useEffect(() => {
    const wakeStatus = statusMessage.toLowerCase()
    const listening = wakeStatus.includes('wake word armed') || wakeStatus.includes('wake word detected') || wakeStatus.includes('listening for your request')
    setIsWakeListening(listening)
  }, [statusMessage])

  const state: JarvisState = useMemo(() => ({
    connectionState,
    statusMessage,
    messages,
    isRecording: uiRecording,
    isSpeaking,
    audioLevel,
    currentTime,
    systemMetrics,
    pendingMailDraft,
    isWakeListening,
    wakeWord: voiceSettings.wakeWord
  }), [connectionState, statusMessage, messages, uiRecording, isSpeaking, audioLevel, currentTime, systemMetrics, pendingMailDraft, isWakeListening, voiceSettings.wakeWord])

  const actions: JarvisActions = useMemo(() => ({
    toggleRecording: handleToggleRecording,
    updateMailDraftField,
    confirmMailDraft,
    cancelMailDraft
  }), [handleToggleRecording, updateMailDraftField, confirmMailDraft, cancelMailDraft])

  return { state, actions }
}
