import { motion } from 'framer-motion'
import { Activity } from 'lucide-react'

interface StatusPanelProps {
  isRecording: boolean
  isSpeaking: boolean
}

export function StatusPanel({ isRecording, isSpeaking }: StatusPanelProps) {
  return (
    <motion.aside
      className="status-panel"
      initial={{ x: 50, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.8, delay: 0.2 }}
    >
      <div className="panel-header">
        <Activity size={18} />
        <span>System Status</span>
      </div>

      <div className="status-grid">
        <div className="status-item">
          <span className="status-label">Core Temp</span>
          <span className="status-value">42°C</span>
        </div>
        <div className="status-item">
          <span className="status-label">Latency</span>
          <span className="status-value">24ms</span>
        </div>
        <div className="status-item">
          <span className="status-label">Audio Stream</span>
          <span className={`status-value ${isRecording ? 'active' : ''}`}>
            {isRecording ? 'ACTIVE' : 'STANDBY'}
          </span>
        </div>
        <div className="status-item">
          <span className="status-label">Neural Net</span>
          <span className={`status-value ${isSpeaking ? 'active' : ''}`}>
            {isSpeaking ? 'PROCESSING' : 'IDLE'}
          </span>
        </div>
      </div>
    </motion.aside>
  )
}
