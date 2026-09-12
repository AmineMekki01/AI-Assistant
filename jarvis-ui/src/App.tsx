import { useState, useMemo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import './App.css'

import { useJarvis } from './hooks/useJarvis'
import { SettingsModal } from './components/settings/SettingsModal'
import { JarvisHUD } from './components/hud/JarvisHUD'
import { Header, MessagesPanel, StatusPanel, Footer } from './components/layout'

function App() {
  const [showSettings, setShowSettings] = useState(false)
  const { state, actions } = useJarvis()

  const { connectionState, statusMessage, messages, isRecording, isSpeaking, audioLevel, currentTime, systemMetrics, pendingMailDraft, isWakeListening, wakeWord, voiceDebug } = state
  const briefingStatusMessage = statusMessage.startsWith('Hang on') ? statusMessage : ''
  const voiceNotice = /unavailable|disabled|rejected|interrupted|enroll|denied|error|failed|crashed|expired|behind|stopped|reopening/i.test(statusMessage) ? statusMessage : ''
  const nativeListening = connectionState === 'connected' && (isWakeListening || Boolean(voiceDebug?.passiveFollowup))

  const timeString = useMemo(() =>
    currentTime.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }),
    [currentTime]
  )

  return (
    <div className="jarvis-app">
      <Header
        status={connectionState}
        isRecording={isRecording}
        isSpeaking={isSpeaking}
        onOpenSettings={() => setShowSettings(true)}
      />

      <main className="jarvis-main">
        <section className="assistant-stage" aria-label="Your assistant">
          <div className="stage-topline">
            <span className="eyebrow">Personal intelligence</span>
            <span className="stage-date">{currentTime.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
          </div>
          <div className="core-container">
            <div className="stage-intro">
              <p className="eyebrow">Just a rather very intelligent system</p>
              <h1>J.A.R.V.I.S.</h1>
              <p className="stage-description">At your service.</p>
            </div>
            <JarvisHUD isSpeaking={isSpeaking} isRecording={isRecording} isListening={nativeListening} audioLevel={audioLevel} />
            <div className="stage-caption" role="status">
              <span className={`presence-dot ${connectionState === 'connected' ? 'online' : ''}`} />
              {connectionState !== 'connected' ? 'Waiting for connection' : isSpeaking ? 'Speaking' : isRecording ? 'Listening' : voiceDebug?.passiveFollowup ? 'Ready for your next request' : isWakeListening ? 'Ready when you are' : 'Voice standby'}
            </div>
            {briefingStatusMessage && <p className="hud-status-message">{briefingStatusMessage}</p>}
            {voiceNotice && <p className="voice-notice" role="alert">{voiceNotice}</p>}
          </div>
          <div className="stage-bottomline">
            <div><span className="eyebrow">Local time</span><span className="time-display">{timeString}</span></div>
            <p>Voice connected to action.<br /><span>Speak naturally. I’ll take it from here.</span></p>
          </div>
        </section>
        <MessagesPanel messages={messages} />
        <StatusPanel
          isRecording={isRecording}
          isSpeaking={isSpeaking}
          systemMetrics={systemMetrics}
          voiceDebug={voiceDebug}
        />
      </main>

      <Footer
        connectionState={connectionState}
        isSpeaking={isSpeaking}
        isRecording={isRecording}
        isWakeListening={isWakeListening}
        followup={Boolean(voiceDebug?.passiveFollowup)}
        wakeWord={wakeWord}
        statusMessage={statusMessage}
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
