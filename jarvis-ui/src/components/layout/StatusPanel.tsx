import { motion } from 'framer-motion'
import { Activity, Gauge, MapPin, Mic, ThermometerSun, Bot, ShieldAlert, Waves, TimerReset } from 'lucide-react'
import type { SystemMetrics, VoiceDebugState } from '../../types'

interface StatusPanelProps {
  isRecording: boolean
  isSpeaking: boolean
  systemMetrics: SystemMetrics | null
  voiceDebug: VoiceDebugState | null
}

export function StatusPanel({ isRecording, isSpeaking, systemMetrics, voiceDebug }: StatusPanelProps) {
  const locationValue = systemMetrics?.location || 'Set in Personal settings'
  const temperatureValue = systemMetrics?.temperature != null
    ? `${Math.round(systemMetrics.temperature)}°${systemMetrics.temperatureUnit === 'fahrenheit' ? 'F' : 'C'}`
    : 'Unavailable'
  const temperatureNote = systemMetrics?.condition || (systemMetrics?.status === 'missing_location' ? 'Add a default location' : 'Live weather data')
  const latencyValue = systemMetrics?.latencyMs != null ? `${Math.round(systemMetrics.latencyMs)}ms` : 'Waiting'
  const voiceStatus = voiceDebug?.status || 'idle'
  const skipReason = voiceDebug?.skipReason || 'No active block'
  const listenerValue = voiceDebug ? (voiceDebug.armed ? 'ARMED' : voiceDebug.passiveFollowup ? 'PASSIVE' : 'LISTENING') : 'UNKNOWN'

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
        <div className="status-item status-item-voice">
          <span className="status-label"><ShieldAlert size={12} /> Voice Diagnostics</span>
          <span className={`status-value ${voiceDebug?.armed ? 'active' : ''}`}>{listenerValue}</span>
          <span className="status-note">{voiceStatus}</span>
          <div className="voice-chip-row">
            <span className={`voice-chip ${voiceDebug?.speaking ? 'active' : ''}`}><Mic size={11} /> {voiceDebug?.speaking ? 'Speaking' : 'Silent'}</span>
            <span className={`voice-chip ${voiceDebug?.musicPlaying ? 'active' : ''}`}><Waves size={11} /> {voiceDebug?.musicPlaying ? 'Music' : 'No music'}</span>
            <span className={`voice-chip ${voiceDebug?.passiveFollowup ? 'active' : ''}`}><TimerReset size={11} /> {voiceDebug?.passiveFollowup ? 'Passive' : 'Wake word'}</span>
          </div>
          <span className="status-note">Skip: {skipReason}</span>
          <span className="status-note compact">
            Cooldown {voiceDebug ? `${voiceDebug.cooldownRemaining.toFixed(1)}s` : 'n/a'} · Mic resume {voiceDebug ? `${voiceDebug.micResumeRemaining.toFixed(1)}s` : 'n/a'} · Window {voiceDebug ? `${voiceDebug.listenWindowRemaining.toFixed(1)}s` : 'n/a'}
          </span>
        </div>
      </div>
    </motion.aside>
  )
}
