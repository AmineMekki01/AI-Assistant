import type { Message, ConnectionState } from '../hooks/useWebSocket'

export type { Message, ConnectionState }

export interface JarvisState {
  connectionState: ConnectionState
  messages: Message[]
  isRecording: boolean
  isSpeaking: boolean
  audioLevel: number
  currentTime: Date
}

export interface JarvisActions {
  toggleRecording: () => void
}
