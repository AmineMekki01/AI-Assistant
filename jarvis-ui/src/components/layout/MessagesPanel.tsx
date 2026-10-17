import { motion, AnimatePresence } from 'framer-motion'
import { Radio, Cpu, Zap, Activity, UserRound } from 'lucide-react'
import type { Message } from '../../types'

interface MessagesPanelProps {
  messages: Message[]
}

function formatTime(timestamp: Date) {
  return timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function MessagesPanel({ messages }: MessagesPanelProps) {
  const recentMessages = messages.slice(-6)

  return (
    <motion.aside
      className="messages-panel"
      initial={{ x: -50, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.8, delay: 0.2 }}
    >
      <div className="panel-header">
        <div className="panel-title">
          <Radio size={18} />
          <span>Conversation Log</span>
        </div>
        <span className="message-count">{messages.length} {messages.length === 1 ? 'entry' : 'entries'}</span>
      </div>

      <div className="messages-list">
        <AnimatePresence mode="popLayout">
          {recentMessages.length === 0 ? (
            <motion.div
              className="empty-state"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              <Cpu size={32} />
              <p>System online. Awaiting input...</p>
              <span>Your conversation will appear here</span>
            </motion.div>
          ) : (
            recentMessages.map((msg, i) => {
              const isAssistant = msg.role === 'assistant'
              const isSystem = msg.role === 'system'
              const label = isSystem ? 'SYSTEM' : isAssistant ? 'JARVIS' : 'YOU'

              return (
                <motion.div
                  key={`${msg.timestamp.getTime()}-${i}`}
                  className={`message-card ${msg.role}`}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  layout
                >
                  <div className="message-avatar" aria-hidden="true">
                    {isSystem ? <Cpu size={14} /> : isAssistant ? <Zap size={14} /> : <UserRound size={14} />}
                  </div>
                  <div className="message-content">
                    <div className="message-meta">
                      <span className="message-role">
                        {isSystem ? <Activity size={11} /> : isAssistant ? <Zap size={11} /> : <UserRound size={11} />}
                        {label}
                      </span>
                      <time dateTime={msg.timestamp.toISOString()}>{formatTime(msg.timestamp)}</time>
                    </div>
                    <div className="message-text">{msg.text}</div>
                  </div>
                </motion.div>
              )
            })
          )}
        </AnimatePresence>
      </div>
    </motion.aside>
  )
}
