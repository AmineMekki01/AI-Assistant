import { motion } from 'framer-motion'
import { Mic, Square, Trash2, Settings } from 'lucide-react'
import { TypingAnimation } from '../ui/TypingAnimation'
import type { Message } from '../../types'

interface FooterProps {
  isSpeaking: boolean
  isRecording: boolean
  isWakeListening: boolean
  wakeWord: string
  latestMessage?: Message
  onToggleRecording: () => void
  onOpenSettings: () => void
}

export function Footer({
  isSpeaking,
  isRecording,
  isWakeListening,
  wakeWord,
  latestMessage,
  onToggleRecording,
  onOpenSettings
}: FooterProps) {
  return (
    <motion.footer
      className="jarvis-footer"
      initial={{ y: 50, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, delay: 0.4 }}
    >
      <div className="message-display">
        {isSpeaking ? (
          <div className="processing-indicator">
            <TypingAnimation />
            <span>JARVIS is responding...</span>
          </div>
        ) : latestMessage ? (
          <motion.p
            className="current-message"
            key={latestMessage.text}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
          >
            {latestMessage.text}
          </motion.p>
        ) : (
          <p className="current-message placeholder">
            Press and hold to speak with JARVIS
          </p>
        )}
      </div>

      <div className="controls-bar">
        <motion.button
          className={`mic-button ${isRecording ? 'recording' : ''}`}
          onClick={onToggleRecording}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.95 }}
          animate={{
            boxShadow: isRecording
              ? ['0 0 30px rgba(239, 68, 68, 0.5)', '0 0 60px rgba(239, 68, 68, 0.8)', '0 0 30px rgba(239, 68, 68, 0.5)']
              : isSpeaking
              ? ['0 0 30px rgba(0, 240, 255, 0.5)', '0 0 60px rgba(0, 240, 255, 0.8)', '0 0 30px rgba(0, 240, 255, 0.5)']
              : '0 0 20px rgba(0, 240, 255, 0.3)'
          }}
          transition={{ duration: 1.5, repeat: Infinity }}
        >
          {isRecording ? <Square size={24} /> : <Mic size={28} />}
        </motion.button>

        <div className="control-hints">
          <span className="hint-main">
            {isRecording ? 'Recording... Click to stop' : 'Say “Hey JARVIS” to begin'}
          </span>
          <span className="hint-sub">
            {isSpeaking
              ? 'JARVIS is speaking'
              : isWakeListening
                ? `Wake word armed — say “${wakeWord}”`
                : 'Voice-controlled AI assistant'}
          </span>
        </div>

        <div className="control-actions">
          <motion.button
            className="icon-button"
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.95 }}
            title="Clear conversation"
          >
            <Trash2 size={20} />
          </motion.button>
          <motion.button
            className="icon-button"
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.95 }}
            onClick={onOpenSettings}
            title="Settings"
          >
            <Settings size={20} />
          </motion.button>
        </div>
      </div>
    </motion.footer>
  )
}
