export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'error'

export interface Message {
  role: 'assistant' | 'user' | 'system'
  text: string
  timestamp: Date
}

export interface BackendStatusMessage {
  type: 'status'
  state: ConnectionState
  message: string
}

export interface BackendConversationMessage {
  type: 'message'
  role: 'assistant' | 'user' | 'system'
  text: string
}

export interface BackendRecordingMessage {
  type: 'recording'
  isRecording: boolean
}

export interface BackendSpeakingMessage {
  type: 'speaking'
  isSpeaking: boolean
}

export type BackendMessage =
  | BackendStatusMessage
  | BackendConversationMessage
  | BackendRecordingMessage
  | BackendSpeakingMessage

export interface JarvisState {
  connectionState: ConnectionState
  statusMessage: string
  messages: Message[]
  isRecording: boolean
  isSpeaking: boolean
  audioLevel: number
  currentTime: Date
}

export interface JarvisActions {
  toggleRecording: () => void
}
