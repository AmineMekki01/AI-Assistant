import { motion } from 'framer-motion'
import { Zap } from 'lucide-react'
import { StatusBadge } from '../ui/StatusBadge'
import type { ConnectionState } from '../../types'

interface HeaderProps {
  status: ConnectionState
  isRecording: boolean
  isSpeaking: boolean
}

export function Header({ status, isRecording, isSpeaking }: HeaderProps) {
  return (
    <motion.header
      className="jarvis-header"
      initial={{ y: -50, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8 }}
    >
      <div className="header-left">
        <motion.div
          className="logo"
          animate={{
            textShadow: isSpeaking
              ? ['0 0 10px rgba(0, 240, 255, 0.5)', '0 0 30px rgba(0, 240, 255, 1)', '0 0 10px rgba(0, 240, 255, 0.5)']
              : '0 0 10px rgba(0, 240, 255, 0.3)'
          }}
          transition={{ duration: 2, repeat: Infinity }}
        >
          <Zap size={24} />
          J.A.R.V.I.S.
        </motion.div>
        <div className="subtitle">Just A Rather Very Intelligent System</div>
      </div>

      <StatusBadge
        status={status}
        isRecording={isRecording}
        isSpeaking={isSpeaking}
      />
    </motion.header>
  )
}
