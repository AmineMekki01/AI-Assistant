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
  const outgoingQueueRef = useRef<string[]>([])

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
  }, [])

  const flushOutgoingQueue = useCallback(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN || outgoingQueueRef.current.length === 0) {
      return
    }

    const pending = outgoingQueueRef.current
    outgoingQueueRef.current = []

    for (const payload of pending) {
      try {
        ws.send(payload)
      } catch (error) {
        outgoingQueueRef.current.unshift(payload)
        console.warn('Failed to flush queued websocket message', error)
        break
      }
    }
  }, [])

  const enqueueOrSend = useCallback((payload: string) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(payload)
        return true
      } catch (error) {
        console.warn('WebSocket send failed, queueing payload for retry', error)
      }
    }

    outgoingQueueRef.current.push(payload)
    return false
  }, [])

  const connect = useCallback(() => {
    if (manuallyClosedRef.current) {
      return
    }

    clearReconnectTimer()

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('Connected to JARVIS backend')
      reconnectAttemptsRef.current = 0
      clearReconnectTimer()
      flushOutgoingQueue()
      setState(prev => ({
        ...prev,
        connectionState: 'connected',
        statusMessage: 'J.A.R.V.I.S. SYSTEM ONLINE'
      }))
    }

    ws.onclose = () => {
      if (manuallyClosedRef.current) {
        return
      }

      console.log('Disconnected from JARVIS backend')
      setState(prev => ({
        ...prev,
        connectionState: 'disconnected',
        statusMessage: 'Connection lost - Retrying...'
      }))
      wsRef.current = null
      
      reconnectAttemptsRef.current += 1
      const delay = Math.min(3000 * reconnectAttemptsRef.current, 15000)
      clearReconnectTimer()
      reconnectTimeoutRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      setState(prev => ({
        ...prev,
        connectionState: 'error',
        statusMessage: 'Connection error'
      }))
    }

    ws.onmessage = async (event) => {
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

      if (!isBackendMessage(incoming)) {
        console.warn('Ignoring unknown backend message shape', describeIncomingPayload(incoming))
        return
      }

      switch (incoming.type) {
        case 'message':
          setState(prev => {
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
            pendingMailDraft: incoming
          }))
          break
      }
    }
  }, [url])

  const disconnect = useCallback(() => {
    manuallyClosedRef.current = true
    clearReconnectTimer()
    outgoingQueueRef.current = []
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [clearReconnectTimer])

  const send = useCallback((data: object) => {
    enqueueOrSend(JSON.stringify(data))
  }, [enqueueOrSend])

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

    console.log('📤 Sending audio chunk, size:', audioData.length, 'base64 length:', base64.length)

    enqueueOrSend(JSON.stringify({
      type: 'audio_chunk',
      data: base64
    }))
  }, [enqueueOrSend])

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
    sendAudioChunk,
    send
  }
}
