interface StatusBadgeProps {
  status: string
  isRecording: boolean
  isSpeaking: boolean
}

export function StatusBadge({ status, isRecording, isSpeaking }: StatusBadgeProps) {
  const online = status === 'connected'
  const label = !online ? status === 'connecting' ? 'Connecting' : 'Offline' : isSpeaking ? 'Speaking' : isRecording ? 'Listening' : 'Connected'
  return <div className={`connection-badge ${online ? 'online' : ''}`} role="status"><span className="status-dot" /><span>{label}</span></div>
}
