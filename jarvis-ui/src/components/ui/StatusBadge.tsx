import { motion } from 'framer-motion'

interface StatusBadgeProps {
  status: string
  isRecording: boolean
  isSpeaking: boolean
}

export function StatusBadge({ status, isRecording, isSpeaking }: StatusBadgeProps) {
  const getStatusColor = () => {
    if (isSpeaking) return '#00f0ff'
    if (isRecording) return '#ef4444'
    if (status === 'connected') return '#10b981'
    if (status === 'connecting') return '#f59e0b'
    return '#64748b'
  }

  const getStatusText = () => {
    if (isSpeaking) return 'SPEAKING'
    if (isRecording) return 'RECORDING'
    if (status === 'connected') return 'ONLINE'
    if (status === 'connecting') return 'CONNECTING'
    return 'OFFLINE'
  }

  return (
    <motion.div
      className="status-badge"
      animate={{
        boxShadow: isSpeaking
          ? ['0 0 20px rgba(0, 240, 255, 0.5)', '0 0 40px rgba(0, 240, 255, 0.8)', '0 0 20px rgba(0, 240, 255, 0.5)']
          : '0 0 10px rgba(0, 0, 0, 0.2)'
      }}
      transition={{ duration: 1, repeat: Infinity }}
    >
      <span
        className="status-dot"
        style={{ backgroundColor: getStatusColor() }}
      />
      <span className="status-text" style={{ color: getStatusColor() }}>
        {getStatusText()}
      </span>
    </motion.div>
  )
}
