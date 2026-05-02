import { useState, useMemo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import './App.css'

import { useJarvis } from './hooks/useJarvis'
import { AudioWaveform } from './components/ui/AudioWaveform'
import { SettingsModal } from './components/settings/SettingsModal'
import { JarvisHUD } from './components/hud/JarvisHUD'
import { Header, MessagesPanel, StatusPanel, Footer } from './components/layout'

function App() {
  const [showSettings, setShowSettings] = useState(false)
  const { state, actions } = useJarvis()

  const { connectionState, statusMessage, messages, isRecording, isSpeaking, audioLevel, currentTime, systemMetrics, pendingMailDraft } = state
  const briefingStatusMessage = statusMessage.startsWith('Hang on') ? statusMessage : ''

  const latestMessage = messages[messages.length - 1]

  const timeString = useMemo(() =>
    currentTime.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }),
    [currentTime]
  )

  const seconds = useMemo(() =>
    currentTime.getSeconds().toString().padStart(2, '0'),
    [currentTime]
  )

  return (
    <div className="jarvis-app">
      <div className="bg-grid" />
      <div className="bg-scanlines" />

      <Header
        status={connectionState}
        isRecording={isRecording}
        isSpeaking={isSpeaking}
      />

      <main className="jarvis-main">
        <MessagesPanel messages={messages} />

        <motion.div
          className="core-container"
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 1, delay: 0.3 }}
        >
          <div className="hud-title">
            <motion.h1
              className="hud-title-main"
              animate={{
                textShadow: isSpeaking
                  ? ['0 0 20px rgba(0, 240, 255, 0.8)', '0 0 40px rgba(0, 240, 255, 1)', '0 0 20px rgba(0, 240, 255, 0.8)']
                  : '0 0 15px rgba(0, 240, 255, 0.5)'
              }}
              transition={{ duration: 1.5, repeat: Infinity }}
            >
              J.A.R.V.I.S 08
            </motion.h1>
            <div className="hud-title-sub">ARTIFICIAL INTELLIGENCE</div>
          </div>

          <JarvisHUD
            isSpeaking={isSpeaking}
            isRecording={isRecording}
            audioLevel={audioLevel}
          />

          {briefingStatusMessage && (
            <motion.div
              className="hud-status-message"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35 }}
            >
              {briefingStatusMessage}
            </motion.div>
          )}

          <div className="time-display">
            <motion.span
              className="time-main"
              animate={{
                color: isSpeaking ? '#00f0ff' : '#ffffff'
              }}
            >
              {timeString}
            </motion.span>
            <span className="time-seconds">:{seconds}</span>
          </div>

          <AudioWaveform isActive={isRecording || isSpeaking} audioLevel={audioLevel} />
        </motion.div>

        <StatusPanel
          isRecording={isRecording}
          isSpeaking={isSpeaking}
          systemMetrics={systemMetrics}
        />
      </main>

      <Footer
        isSpeaking={isSpeaking}
        isRecording={isRecording}
        latestMessage={latestMessage}
        onToggleRecording={actions.toggleRecording}
        onOpenSettings={() => setShowSettings(true)}
      />

      <AnimatePresence>
        {showSettings && (
          <SettingsModal onClose={() => setShowSettings(false)} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {pendingMailDraft && (
          <motion.div
            className="mail-draft-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={actions.cancelMailDraft}
          >
            <motion.div
              className="mail-draft-modal"
              initial={{ y: 24, scale: 0.98, opacity: 0 }}
              animate={{ y: 0, scale: 1, opacity: 1 }}
              exit={{ y: 16, scale: 0.98, opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={e => e.stopPropagation()}
            >
              <div className="mail-draft-header">
                <div>
                  <p className="mail-draft-kicker">Email review</p>
                  <h2>Confirm before sending</h2>
                </div>
                <button className="mail-draft-close" onClick={actions.cancelMailDraft} aria-label="Cancel mail draft">×</button>
              </div>

              <div className="mail-draft-meta">
                <div><span>From</span><strong>{pendingMailDraft.account === 'gmail' ? 'Gmail account' : 'Zimbra account'}</strong></div>
                <label>
                  <span>To</span>
                  <input
                    value={pendingMailDraft.to}
                    onChange={e => actions.updateMailDraftField('to', e.target.value)}
                  />
                </label>
                <label>
                  <span>Subject</span>
                  <input
                    value={pendingMailDraft.subject}
                    onChange={e => actions.updateMailDraftField('subject', e.target.value)}
                  />
                </label>
              </div>

              <div className="mail-draft-body">
                <span>Body</span>
                <textarea
                  value={pendingMailDraft.body}
                  onChange={e => actions.updateMailDraftField('body', e.target.value)}
                />
              </div>

              <div className="mail-draft-actions">
                <button className="mail-draft-secondary" onClick={actions.cancelMailDraft}>Cancel</button>
                <button className="mail-draft-primary" onClick={actions.confirmMailDraft}>Yes, send it</button>
              </div>

              <p className="mail-draft-help">
                You can also confirm by voice with “yes” or “send it”.
              </p>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default App