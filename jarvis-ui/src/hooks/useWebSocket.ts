import { useState, useRef, useCallback, useEffect } from 'react'

export interface Message {
  role: 'assistant' | 'user' | 'system'
  text: string
  timestamp: Date
}

export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error'

interface WebSocketState {
  connectionState: ConnectionState
  statusMessage: string
  messages: Message[]
  isRecording: boolean
  isSpeaking: boolean
}

export function useWebSocket(url: string) {
  const [state, setState] = useState<WebSocketState>({
    connectionState: 'connecting',
    statusMessage: 'Connecting to JARVIS...',
    messages: [],
    isRecording: false,
    isSpeaking: false
  })

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('Connected to JARVIS backend')
      setState(prev => ({
        ...prev,
        connectionState: 'connected',
        statusMessage: 'J.A.R.V.I.S. SYSTEM ONLINE'
      }))
    }

    ws.onclose = () => {
      console.log('Disconnected from JARVIS backend')
      setState(prev => ({
        ...prev,
        connectionState: 'disconnected',
        statusMessage: 'Connection lost - Retrying...'
      }))
      wsRef.current = null
      
      reconnectTimeoutRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      setState(prev => ({
        ...prev,
        connectionState: 'error',
        statusMessage: 'Connection error'
      }))
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)

      switch (data.type) {
        case 'message':
          setState(prev => {
            const lastMsg = prev.messages[prev.messages.length - 1]
            if (lastMsg && lastMsg.role === data.role && data.role === 'assistant') {
              return {
                ...prev,
                messages: [
                  ...prev.messages.slice(0, -1),
                  {
                    role: data.role,
                    text: data.text,
                    timestamp: lastMsg.timestamp
                  }
                ]
              }
            }
            return {
              ...prev,
              messages: [...prev.messages, {
                role: data.role,
                text: data.text,
                timestamp: new Date()
              }]
            }
          })
          break

        case 'status':
          setState(prev => ({
            ...prev,
            connectionState: data.state,
            statusMessage: data.message
          }))
          break

        case 'recording':
          setState(prev => ({
            ...prev,
            isRecording: data.isRecording
          }))
          break
          
        case 'speaking':
          setState(prev => ({
            ...prev,
            isSpeaking: data.isSpeaking
          }))
          console.log('🔊 JARVIS speaking:', data.isSpeaking)
          break
      }
    }
  }, [url])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const send = useCallback((data: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  const toggleRecording = useCallback(() => {
    send({ type: 'toggle_recording' })
  }, [send])

  const sendAudioChunk = useCallback((audioData: Float32Array) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const bytes = new Uint8Array(audioData.buffer)
      const base64 = btoa(String.fromCharCode(...bytes))
      
      console.log('📤 Sending audio chunk, size:', audioData.length, 'base64 length:', base64.length)
      
      wsRef.current.send(JSON.stringify({
        type: 'audio_chunk',
        data: base64
      }))
    } else {
      console.warn('⚠️ WebSocket not open, cannot send audio')
    }
  }, [])

  useEffect(() => {
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
