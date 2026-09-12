import { AudioLines } from 'lucide-react'
import type { ConnectionState } from '../../types'

interface FooterProps {
  connectionState: ConnectionState
  isSpeaking: boolean
  isRecording: boolean
  isWakeListening: boolean
  followup: boolean
  wakeWord: string
  statusMessage: string
}

export function Footer({ connectionState, isSpeaking, isRecording, isWakeListening, followup, wakeWord, statusMessage }: FooterProps) {
  const online = connectionState === 'connected'
  const hint = !online ? 'Waiting for JARVIS to connect' : isSpeaking ? 'JARVIS is responding' : isRecording ? 'Listening to you' : followup ? 'Go ahead, I’m listening' : isWakeListening ? `Say “${wakeWord}” to begin` : 'Voice standby'
  return (
    <footer className="jarvis-footer">
      <div className="voice-presence" role="status"><AudioLines size={18} /><span>{hint}</span></div>
      <span className="footer-note">{online && (isWakeListening || followup || isRecording || isSpeaking) ? 'Hands-free · No buttons needed' : statusMessage || 'Your assistant, a conversation away'}</span>
    </footer>
  )
}
