import { motion } from 'framer-motion'
import { Activity, Gauge, MapPin, Mic, ThermometerSun, Bot } from 'lucide-react'
import type { SystemMetrics } from '../../types'

interface StatusPanelProps {
  isRecording: boolean
  isSpeaking: boolean
  systemMetrics: SystemMetrics | null
}

export function StatusPanel({ isRecording, isSpeaking, systemMetrics }: StatusPanelProps) {
  const locationValue = systemMetrics?.location || 'Set in Personal settings'
  const temperatureValue = systemMetrics?.temperature != null
    ? `${Math.round(systemMetrics.temperature)}°${systemMetrics.temperatureUnit === 'fahrenheit' ? 'F' : 'C'}`
    : 'Unavailable'
  const temperatureNote = systemMetrics?.condition || (systemMetrics?.status === 'missing_location' ? 'Add a default location' : 'Live weather data')
  const latencyValue = systemMetrics?.latencyMs != null ? `${Math.round(systemMetrics.latencyMs)}ms` : 'Waiting'

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
          <span className="status-label"><MapPin size={12} /> Location</span>
          <span className={`status-value ${systemMetrics?.status === 'ok' ? 'active' : ''}`}>{locationValue}</span>
        </div>
        <div className="status-item">
          <span className="status-label"><ThermometerSun size={12} /> Temperature</span>
          <span className={`status-value ${systemMetrics?.temperature != null ? 'active' : ''}`}>
            {temperatureValue}
          </span>
          <span className="status-note">{temperatureNote}</span>
        </div>
        <div className="status-item">
          <span className="status-label"><Gauge size={12} /> Latency</span>
          <span className={`status-value ${systemMetrics?.latencyMs != null ? 'active' : ''}`}>{latencyValue}</span>
          <span className="status-note">Backend round-trip</span>
        </div>
        <div className="status-item">
          <span className="status-label"><Mic size={12} /> Audio Stream</span>
          <span className={`status-value ${isRecording ? 'active' : ''}`}>
            {isRecording ? 'ACTIVE' : 'STANDBY'}
          </span>
        </div>
        <div className="status-item">
          <span className="status-label"><Bot size={12} /> Neural Net</span>
          <span className={`status-value ${isSpeaking ? 'active' : ''}`}>
            {isSpeaking ? 'PROCESSING' : 'IDLE'}
          </span>
        </div>
      </div>
    </motion.aside>
  )
}
