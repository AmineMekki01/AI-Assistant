import { motion, AnimatePresence } from 'framer-motion'
import { Radio, Cpu, Zap, Activity } from 'lucide-react'
import type { Message } from '../../types'

interface MessagesPanelProps {
  messages: Message[]
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
        <Radio size={18} />
        <span>Conversation Log</span>
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
            </motion.div>
          ) : (
            recentMessages.map((msg, i) => (
              <motion.div
                key={i}
                className={`message-card ${msg.role}`}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                layout
              >
                <div className="message-role">
                  {msg.role === 'assistant' ? (
                    <><Zap size={12} /> JARVIS</>
                  ) : (
                    <><Activity size={12} /> USER</>
                  )}
                </div>
                <div className="message-text">{msg.text}</div>
              </motion.div>
            ))
          )}
        </AnimatePresence>
      </div>
    </motion.aside>
  )
}
