import { useState, useRef, useCallback, useEffect } from 'react'
import type { BackendMessage, ConnectionState, Message, BackendMailDraftMessage, VoiceDebugState } from '../types'

interface WebSocketState {
  connectionState: ConnectionState
  statusMessage: string
  messages: Message[]
  isRecording: boolean
  isSpeaking: boolean
  voiceDebug: VoiceDebugState | null
  pendingMailDraft: BackendMailDraftMessage | null
}

function isBackendMessage(data: unknown): data is BackendMessage {
  if (!data || typeof data !== 'object') {
    return false
  }

  const payload = data as Record<string, unknown>
  if (typeof payload.type !== 'string') {
    return false
  }

  switch (payload.type) {
    case 'status':
      return typeof payload.state === 'string' && typeof payload.message === 'string'
    case 'message':
      return typeof payload.role === 'string' && typeof payload.text === 'string'
    case 'recording':
      return typeof payload.isRecording === 'boolean'
    case 'speaking':
      return typeof payload.isSpeaking === 'boolean'
    case 'voice_debug':
      return typeof payload.armed === 'boolean'
        && typeof payload.speaking === 'boolean'
        && typeof payload.musicPlaying === 'boolean'
        && typeof payload.passiveFollowup === 'boolean'
        && typeof payload.recording === 'boolean'
        && typeof payload.skipReason === 'string'
        && typeof payload.cooldownRemaining === 'number'
        && typeof payload.micResumeRemaining === 'number'
        && typeof payload.listenWindowRemaining === 'number'
        && typeof payload.status === 'string'
    case 'mail_draft':
      return typeof payload.account === 'string'
        && typeof payload.to === 'string'
        && typeof payload.subject === 'string'
        && typeof payload.body === 'string'
        && typeof payload.rawText === 'string'
    default:
      return false
  }
}

function describeIncomingPayload(payload: unknown): string {
  if (typeof payload === 'string') {
    return payload.length > 160 ? `${payload.slice(0, 160)}…` : payload
  }

  if (payload instanceof Blob) {
    return `[Blob size=${payload.size} type=${payload.type || 'unknown'}]`
  }

  if (payload instanceof ArrayBuffer) {
    return `[ArrayBuffer byteLength=${payload.byteLength}]`
  }

  if (ArrayBuffer.isView(payload)) {
    return `[${payload.constructor.name} byteLength=${payload.byteLength}]`
  }

  if (payload && typeof payload === 'object') {
    try {
      return JSON.stringify(payload)
    } catch {
      return '[Unserializable object]'
    }
  }

  return String(payload)
}

export function useWebSocket(url: string) {
  const [state, setState] = useState<WebSocketState>({
    connectionState: 'connecting',
    statusMessage: 'Connecting to JARVIS...',
    messages: [],
    isRecording: false,
    isSpeaking: false,
    voiceDebug: null,
    pendingMailDraft: null
  })

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const manuallyClosedRef = useRef(false)

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (manuallyClosedRef.current) {
      return
    }

    clearReconnectTimer()

    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (wsRef.current !== ws) return
      console.log('Connected to JARVIS backend')
      reconnectAttemptsRef.current = 0
      clearReconnectTimer()
      setState(prev => ({
        ...prev,
        connectionState: 'connected',
        statusMessage: 'J.A.R.V.I.S. SYSTEM ONLINE'
      }))
    }

    ws.onclose = () => {
      if (manuallyClosedRef.current || wsRef.current !== ws) {
        return
      }

      console.log('Disconnected from JARVIS backend')
      setState(prev => ({
        ...prev,
        connectionState: 'disconnected',
        isRecording: false,
        isSpeaking: false,
        voiceDebug: null,
        statusMessage: 'Connection lost - Retrying...'
      }))
      wsRef.current = null
      
      reconnectAttemptsRef.current += 1
      const delay = Math.min(3000 * reconnectAttemptsRef.current, 15000)
      clearReconnectTimer()
      reconnectTimeoutRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      if (wsRef.current !== ws) return
      setState(prev => ({
        ...prev,
        connectionState: 'error',
        statusMessage: 'Connection error'
      }))
    }

    ws.onmessage = async (event) => {
      if (wsRef.current !== ws) return
      const raw = event.data as unknown
      let incoming: unknown = raw

      try {
        if (typeof raw === 'string') {
          incoming = JSON.parse(raw)
        } else if (raw instanceof Blob) {
          incoming = JSON.parse(await raw.text())
        } else if (raw instanceof ArrayBuffer) {
          incoming = JSON.parse(new TextDecoder().decode(raw))
        } else if (ArrayBuffer.isView(raw)) {
          incoming = JSON.parse(new TextDecoder().decode(raw.buffer))
        }
      } catch {
        console.warn('Ignoring malformed backend message', describeIncomingPayload(raw))
        return
      }

      if (wsRef.current !== ws) return
      if (!isBackendMessage(incoming)) {
        console.warn('Ignoring unknown backend message shape', describeIncomingPayload(incoming))
        return
      }

      switch (incoming.type) {
        case 'message':
          setState(prev => {
            if (incoming.id) {
              const index = prev.messages.findIndex(message => message.id === incoming.id)
              if (index >= 0) {
                const messages = [...prev.messages]
                messages[index] = { ...messages[index], text: incoming.text }
                return { ...prev, messages }
              }
              return { ...prev, messages: [...prev.messages, {
                id: incoming.id, role: incoming.role, text: incoming.text, timestamp: new Date()
              }] }
            }
            const lastMsg = prev.messages[prev.messages.length - 1]
            if (lastMsg && lastMsg.role === incoming.role && incoming.role === 'assistant') {
              return {
                ...prev,
                messages: [
                  ...prev.messages.slice(0, -1),
                  {
                    role: incoming.role,
                    text: incoming.text,
                    timestamp: lastMsg.timestamp
                  }
                ]
              }
            }
            return {
              ...prev,
              messages: [...prev.messages, {
                role: incoming.role,
                text: incoming.text,
                timestamp: new Date()
              }]
            }
          })
          break

        case 'status':
          setState(prev => ({
            ...prev,
            connectionState: incoming.state,
            statusMessage: incoming.message
          }))
          break

        case 'recording':
          setState(prev => ({
            ...prev,
            isRecording: incoming.isRecording
          }))
          break
          
        case 'speaking':
          setState(prev => ({
            ...prev,
            isSpeaking: incoming.isSpeaking
          }))
          console.log('🔊 JARVIS speaking:', incoming.isSpeaking)
          break

        case 'voice_debug':
          console.log(
            '🫀 Voice debug:',
            incoming.status,
            `armed=${incoming.armed}`,
            `speaking=${incoming.speaking}`,
            `music=${incoming.musicPlaying}`,
            `passive=${incoming.passiveFollowup}`,
            `skip=${incoming.skipReason || 'none'}`,
            `cooldown=${incoming.cooldownRemaining.toFixed(1)}s`,
            `mic=${incoming.micResumeRemaining.toFixed(1)}s`,
            `window=${incoming.listenWindowRemaining.toFixed(1)}s`
          )
          setState(prev => ({
            ...prev,
            voiceDebug: incoming
          }))
          break

        case 'mail_draft':
          setState(prev => ({
            ...prev,
            pendingMailDraft: incoming.cleared ? null : incoming
          }))
          break
      }
    }
  }, [url])

  const disconnect = useCallback(() => {
    manuallyClosedRef.current = true
    clearReconnectTimer()
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [clearReconnectTimer])

  const send = useCallback((data: object) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setState(prev => ({ ...prev, statusMessage: 'Connection unavailable — please retry when connected' }))
      return false
    }
    ws.send(JSON.stringify(data))
    return true
  }, [])

  const toggleRecording = useCallback(() => {
    send({ type: 'toggle_recording' })
  }, [send])

  const sendAudioChunk = useCallback((audioData: Float32Array) => {
    const bytes = new Uint8Array(audioData.buffer, audioData.byteOffset, audioData.byteLength)
    let binary = ''
    const chunkSize = 0x8000
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize))
    }
    const base64 = btoa(binary)

    // Live audio expires immediately. Replaying a disconnected microphone
    // backlog can execute a request long after the user spoke it.
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 128 * 1024) return
    ws.send(JSON.stringify({ type: 'audio_chunk', data: base64 }))
  }, [])

  const setRecording = useCallback((isRecording: boolean) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    ws.send(JSON.stringify({ type: 'set_recording', isRecording }))
    return true
  }, [])

  useEffect(() => {
    manuallyClosedRef.current = false
    connect()
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  return {
    ...state,
    toggleRecording,
    setRecording,
    sendAudioChunk,
    send
  }
}
