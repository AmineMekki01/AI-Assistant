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

  const { connectionState, messages, isRecording, isSpeaking, audioLevel, currentTime } = state

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

        <StatusPanel isRecording={isRecording} isSpeaking={isSpeaking} />
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
    </div>
  )
}

export default App