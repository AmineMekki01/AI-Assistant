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

export interface BackendMailDraftMessage {
  type: 'mail_draft'
  account: 'gmail' | 'zimbra'
  to: string
  subject: string
  body: string
  rawText: string
}

export interface SystemMetrics {
  location: string
  temperature: number | null
  temperatureUnit: 'celsius' | 'fahrenheit'
  condition: string | null
  latencyMs: number | null
  status: 'ok' | 'missing_location' | 'error'
  updatedAt: number | null
}

export interface MailDraft {
  account: 'gmail' | 'zimbra'
  to: string
  subject: string
  body: string
  rawText: string
}

export type BackendMessage =
  | BackendStatusMessage
  | BackendConversationMessage
  | BackendRecordingMessage
  | BackendSpeakingMessage
  | BackendMailDraftMessage

export interface JarvisState {
  connectionState: ConnectionState
  statusMessage: string
  messages: Message[]
  isRecording: boolean
  isSpeaking: boolean
  audioLevel: number
  currentTime: Date
  systemMetrics: SystemMetrics | null
  pendingMailDraft: MailDraft | null
  isWakeListening: boolean
  wakeWord: string
}

export interface JarvisActions {
  toggleRecording: () => void
  updateMailDraftField: (field: 'to' | 'subject' | 'body', value: string) => void
  confirmMailDraft: () => void
  cancelMailDraft: () => void
}
